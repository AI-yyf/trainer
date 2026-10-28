from __future__ import annotations

import copy
import logging
import re
import socket
import ssl
from typing import TypedDict, cast

from ..core.models import (
    CardGenerationRequest,
    SessionMessageRequest,
    TurnRequest,
)
from ..llm.provider_service import (
    ProviderService,
)
from ..memory.workspace_recovery import (
    CURRENT_TASK_KEY,
    PLAN_RUNTIME_KEY,
    formal_plan_is_live_runtime_identity,
    formal_task_is_live_runtime_identity,
    leftover_formal_training_labels,
    live_training_mint_anchors,
    normalize_latest_current_task,
    select_plan_runtime_for_scope,
)
from .runtime import TrainerRuntime

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



def looks_like_schemeless_provider_host(value: str) -> bool:
    """True for host-style service addresses a user typed without a scheme."""
    if not value or re.search(r"\s", value):
        return False
    if _SCHEMELESS_PROVIDER_HOST_RE.match(value):
        return True
    return bool(_SCHEMELESS_LOCAL_HOST_WITH_PORT_RE.match(value))


def _probe_provider_url_scheme(host: str, port: int) -> str | None:
    """Connect and attempt a TLS handshake; None when unreachable."""
    try:
        raw_socket = socket.create_connection((host, port), timeout=0.8)
    except OSError:
        return None
    try:
        with raw_socket:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            try:
                with context.wrap_socket(raw_socket, server_hostname=host):
                    return "https"
            except (ssl.SSLError, OSError):
                return "http"
    except OSError:
        return None


def resolve_provider_url_scheme(value: str) -> str:
    """Pick http/https for a scheme-less service address by probing.

    Local and private hosts are http without probing; public hosts get a TLS
    handshake probe on their port so http-only relays (no 443) still work
    instead of failing later with an opaque request error.
    """
    authority = value.split("/", 1)[0]
    host = authority.split(":", 1)[0].lower().strip("[]")
    port_part = authority.split(":", 1)[1] if ":" in authority else ""
    try:
        explicit_port = int(port_part) if port_part else None
    except ValueError:
        explicit_port = None
    if _LOCAL_PROVIDER_HOST_RE.match(host):
        return "http"
    cache_key = f"{host}:{explicit_port or 0}"
    cached = _PROVIDER_SCHEME_CACHE.get(cache_key)
    if cached:
        return cached
    ports = [explicit_port] if explicit_port else [443, 80]
    resolved = "https"
    for port in ports:
        probed = _probe_provider_url_scheme(host, port)
        if probed is not None:
            resolved = probed
            break
    _PROVIDER_SCHEME_CACHE[cache_key] = resolved
    return resolved


def reset_provider_scheme_cache() -> None:
    """Clear memoized scheme resolutions (test isolation)."""
    _PROVIDER_SCHEME_CACHE.clear()


def provider_recovery_resumed_summary_text(response_language: str | None) -> str:
    if response_language and response_language.lower().startswith("zh"):
        return "Provider 连接已恢复。继续当前学习主线，只完成一个小而可验证的动作。"
    return "Provider connection recovered. Continue the current learning lane with one small, verifiable action."


def provider_recovery_resumed_next_step_text(
    scenario: str,
    response_language: str | None,
) -> str:
    normalized = str(scenario or "").strip().lower()
    if normalized == "remote_workspace":
        return (
            "在你当前的 VS Code 窗口里，带回一个能证明工作区落点的真实信号，比如 Explorer 里的路径、终端里的 `pwd`，"
            "或者左下角的 remote host 标签。"
            if response_language and response_language.lower().startswith("zh")
            else "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label."
        )
    if normalized == "debug_loop":
        return (
            "告诉我你会先停在哪个断点，以及准备先检查哪一个值、分支或 stack frame。"
            if response_language and response_language.lower().startswith("zh")
            else "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect."
        )
    if normalized == "function_guidance":
        return (
            "给我函数名，以及你现在就能打开的一个 call site。"
            if response_language and response_language.lower().startswith("zh")
            else "Give me the function name and one call site you can open right now."
        )
    if normalized == "project_adaptation":
        return (
            "告诉我什么必须保持稳定、什么必须改变，以及你想先适配的第一条边界。"
            if response_language and response_language.lower().startswith("zh")
            else "Tell me what must stay stable, what must change, and the first boundary you want to adapt."
        )
    if response_language and response_language.lower().startswith("zh"):
        return "从最近的说明里选一个最小可验证动作，然后带着结果回来。"
    return "Take the smallest verifiable action from the latest explanation, then return with what happened."


def _pedagogy_controls_for_workspace(runtime: TrainerRuntime, workspace_id: str):
    from ..pedagogy.evidence_controls import controls_from_profile

    memory = runtime.memory_service.snapshot(workspace_id)
    return controls_from_profile(getattr(memory, "coaching_adaptation", None))


class _TrainingMintOverlay(TypedDict):
    anchors: dict[str, str]
    leftover: set[str]
    recovered_step: str


def _workspace_training_mint_overlay(
    runtime: TrainerRuntime,
    workspace_id: str,
    request_payload: CardGenerationRequest,
) -> _TrainingMintOverlay:
    """Strip leftover formal title/summary from card mint anchors."""

    repository = getattr(runtime, "repository", None)
    plan = repository.get_latest_plan(workspace_id) if repository is not None else None
    memory = runtime.memory_service.snapshot(workspace_id)
    workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
    plan_runtime = select_plan_runtime_for_scope(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        workspace_id,
    ) or {}
    task = normalize_latest_current_task(
        workspace.get(CURRENT_TASK_KEY)
        or workspace.get("current_task")
        or workspace.get("currentTask"),
        workspace_id,
    ) or {}
    task_title = str(task.get("title") or "").strip()
    recovered_step = str(plan_runtime.get("current_step") or "").strip()
    live_plan = formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=plan_runtime,
        existing=plan_runtime,
        current_step=recovered_step,
    )
    live_task = formal_task_is_live_runtime_identity(
        recovered=bool(plan_runtime),
        runtime_current_step=recovered_step,
        task_title=task_title,
    )
    anchors = live_training_mint_anchors(
        plan=plan,
        runtime=plan_runtime,
        existing=plan_runtime,
        task_title=task_title,
        why_now=request_payload.why_now,
        target_skill=request_payload.target_skill,
        focus_area=request_payload.focus_area,
    )
    leftover = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=live_plan,
        live_task=live_task,
    )
    return {
        "anchors": anchors,
        "leftover": leftover,
        "recovered_step": recovered_step,
    }


def _apply_pedagogy_controls_to_card_request(request_payload: CardGenerationRequest, runtime: TrainerRuntime):
    from ..pedagogy.evidence_controls import apply_controls_to_context

    controls = _pedagogy_controls_for_workspace(runtime, request_payload.workspace_id)
    if controls is None:
        return request_payload
    difficulty = str(request_payload.difficulty or "").strip().lower()
    if difficulty in {"", "medium"}:
        return apply_controls_to_context(request_payload, controls)
    return request_payload.model_copy(
        update={
            "hint_count": request_payload.hint_count or controls.hint_count,
            "code_reveal": request_payload.code_reveal or controls.code_reveal,
            "practice_type": request_payload.practice_type or controls.practice_type,
            "review_frequency": request_payload.review_frequency or controls.review_frequency,
            "material_recommendation": request_payload.material_recommendation
            or controls.material_recommendation,
            "next_plan_step": request_payload.next_plan_step or controls.next_plan_step,
            "should_reveal_code": (
                request_payload.should_reveal_code
                if request_payload.should_reveal_code is not None
                else controls.should_reveal_code
            ),
            "pedagogy_mode": request_payload.pedagogy_mode or controls.pedagogy_mode,
        }
    )


def _request_is_plan_agent_turn(
    request: TurnRequest | SessionMessageRequest,
    payload: dict | None = None,
) -> bool:
    """Plan discussion and revision share the executable planning loop."""

    if str(getattr(request, "active_view", "") or "").strip().lower() == "plan":
        return True
    if str(getattr(request, "intent", "") or "").strip().lower() == "plan":
        return True
    if not isinstance(payload, dict):
        return False
    raw_intent = str(payload.get("intent") or "").strip().lower()
    if raw_intent == "plan":
        return True
    raw_view = str(payload.get("active_view") or payload.get("activeView") or "").strip().lower()
    return raw_view == "plan"


def _request_is_library_agent_turn(
    request: TurnRequest | SessionMessageRequest,
    payload: dict | None = None,
) -> bool:
    """Resources library work uses the same executable agent loop as formal-plan turns."""

    if str(getattr(request, "active_view", "") or "").strip().lower() == "resources":
        return True
    if str(getattr(request, "intent", "") or "").strip().lower() == "resources":
        return True
    if getattr(request, "resource_composer_intent", None) is not None:
        return True
    if not isinstance(payload, dict):
        return False
    raw_intent = str(payload.get("intent") or "").strip().lower()
    if raw_intent == "resources":
        return True
    raw_view = str(payload.get("active_view") or payload.get("activeView") or "").strip().lower()
    return raw_view == "resources"


def _workspace_snapshot_from_payload(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    snapshot = payload.get("workspace_file_snapshot") or payload.get("workspaceFileSnapshot")
    return snapshot if isinstance(snapshot, dict) and snapshot else None


def _attach_requested_workspace_files(
    payload: dict[str, object],
    runtime: object,
    workspace_id: str | None,
) -> dict[str, object]:
    getter = getattr(runtime, "requested_workspace_file_paths", None)
    files = cast("list[str]", getter(workspace_id)) if callable(getter) else []
    if not files:
        return payload
    payload["requested_workspace_files"] = list(files)
    payload["requestedWorkspaceFiles"] = list(files)
    return payload


def _stamp_library_sandbox_work(
    coach_context: dict[str, object] | None,
    request: TurnRequest | SessionMessageRequest,
    payload: dict | None = None,
) -> None:
    if not isinstance(coach_context, dict):
        return
    snapshot = getattr(request, "workspace_file_snapshot", None)
    if snapshot is None and isinstance(payload, dict):
        snapshot = payload.get("workspace_file_snapshot") or payload.get("workspaceFileSnapshot")
    if isinstance(snapshot, dict) and snapshot:
        coach_context["workspace_file_snapshot"] = snapshot
        if snapshot.get("is_remote") is True:
            coach_context["library_sandbox_work"] = True
    if _request_is_library_agent_turn(request, payload):
        coach_context["library_sandbox_work"] = True
    composer = getattr(request, "resource_composer_intent", None)
    if composer is None:
        return
    mode = str(getattr(composer, "mode", "") or "").strip().lower()
    coach_context["resource_composer_intent"] = {
        "mode": mode,
        "resource_ids": list(getattr(composer, "resource_ids", []) or []),
    }
    if mode == "download":
        coach_context["explicit_resource_import"] = True
    if mode == "organize":
        coach_context["explicit_resource_organize"] = True


def _resolve_agent_loop_enabled(
    request: TurnRequest | SessionMessageRequest,
    coaching_service: ProviderService,
    *,
    stream: bool = False,
    payload: dict | None = None,
) -> bool:
    """Choose the tool loop only for requests that need executable tool authority."""
    config = getattr(coaching_service, "_config", None)
    capabilities = getattr(config, "capabilities", None) if config is not None else None
    supports_tools = getattr(coaching_service, "supports_executable_tools", None)
    provider_supports_tools = (
        bool(supports_tools())
        if callable(supports_tools)
        else bool(
            coaching_service.has_api_key
            and capabilities is not None
            and bool(getattr(capabilities, "tools", False))
        )
    )
    formal_plan_turn = bool(
        isinstance(request, TurnRequest)
        and request.intent == "plan"
        and request.formal_plan_mutation
    )
    snapshot = getattr(request, "workspace_file_snapshot", None)
    if snapshot is None and isinstance(payload, dict):
        snapshot = payload.get("workspace_file_snapshot") or payload.get("workspaceFileSnapshot")
    remote_workspace_turn = isinstance(snapshot, dict) and snapshot.get("is_remote") is True
    if remote_workspace_turn and provider_supports_tools:
        return True
    if formal_plan_turn:
        # A formal plan is a model-authored mutation. Never silently downgrade
        # it to the local planner when the caller omitted useAgentLoop.
        return provider_supports_tools
    if _request_is_plan_agent_turn(request, payload):
        explicit_flag = request.use_agent_loop
        if explicit_flag is None and isinstance(payload, dict):
            if "use_agent_loop" in payload:
                explicit_flag = payload.get("use_agent_loop")
            elif "useAgentLoop" in payload:
                explicit_flag = payload.get("useAgentLoop")
        if explicit_flag is False:
            return False
        return provider_supports_tools
    if _request_is_library_agent_turn(request, payload):
        # Resources/library turns need the same ReAct loop so the coach can
        # list, edit, and index the managed sandbox instead of talking about it.
        # An explicit false still lets a host keep a resources discussion on
        # the plain model stream.
        explicit_flag = request.use_agent_loop
        if explicit_flag is None and isinstance(payload, dict):
            if "use_agent_loop" in payload:
                explicit_flag = payload.get("use_agent_loop")
            elif "useAgentLoop" in payload:
                explicit_flag = payload.get("useAgentLoop")
        if explicit_flag is False:
            return False
        return provider_supports_tools
    # Images use the independently verified vision/image transport gate; file
    # attachments require the executable tools binding for grounded reads.
    if request.attachments:
        return bool(
            coaching_service.has_api_key
            and all(getattr(attachment, "kind", "image") == "image" for attachment in request.attachments)
        )
    if request.use_agent_loop is not None:
        # Explicit Agent requests must have a verified tools capability in both
        # buffered and streaming paths. The previous non-streaming branch
        # accepted any keyed provider, then failed later inside tool binding.
        return bool(request.use_agent_loop) and provider_supports_tools
    # Plan discussion and Training feedback stay on the model stream unless the
    # host asked for tools. Resources/library work is handled above.
    return False


def _request_requires_agent_tools(request: TurnRequest | SessionMessageRequest) -> bool:
    """Return whether a request needs verified executable tool authority."""
    formal_plan_turn = bool(
        isinstance(request, TurnRequest)
        and request.intent == "plan"
        and request.formal_plan_mutation
    )
    # Image attachments use the independent vision gate; file attachments
    # require verified tools because they need grounded file access.
    if formal_plan_turn:
        return True
    if request.attachments:
        return any(getattr(attachment, "kind", "image") == "file" for attachment in request.attachments)
    return request.use_agent_loop is True


def _normalize_resource_turn_request(request: TurnRequest) -> TurnRequest:
    """Treat the Resources composer lane as a grounded coach turn internally."""
    if request.intent != "resources":
        return request
    return request.model_copy(update={"intent": "coach"})


def overlay_session_response_honesty_stamps(
    payload: dict[str, object],
    *,
    pressure_blocks: bool = False,
    streak_blocks: bool = False,
    recovered_leftover: bool = False,
) -> dict[str, object]:
    """Fail-closed: ensure honesty stamps on a (possibly cached) session payload.

    Completed-session request dedup must not serve an older snapshot that dropped
    pressure/streak mint-blocks or leftover-not-live recovered after a later hydrate.
    Stamps are additive only (never cleared).
    """
    if not pressure_blocks and not streak_blocks and not recovered_leftover:
        return payload

    out = copy.deepcopy(payload)

    def _stamp_mapping(target: dict[str, object]) -> None:
        if pressure_blocks:
            target["pressure_blocks_live_object_mint"] = True
        if streak_blocks:
            target["streak_blocks_live_object_mint"] = True

    if pressure_blocks or streak_blocks:
        raw_agent_meta = out.get("agent_meta")
        if not isinstance(raw_agent_meta, dict):
            raw_agent_meta = out.get("agent")
        agent_meta: dict[str, object] = (
            dict(raw_agent_meta) if isinstance(raw_agent_meta, dict) else {"agentic": False}
        )
        _stamp_mapping(agent_meta)
        out["agent_meta"] = agent_meta
        out["agent"] = agent_meta

        coach_turn = out.get("coach_turn")
        if isinstance(coach_turn, dict):
            coach_turn = dict(coach_turn)
            out["coach_turn"] = coach_turn
            ctx = coach_turn.get("coach_context") or coach_turn.get("coachContext")
            if not isinstance(ctx, dict):
                ctx = {}
            else:
                ctx = dict(ctx)
            coach_turn["coach_context"] = ctx
            _stamp_mapping(ctx)

        reply = out.get("reply")
        if isinstance(reply, dict):
            reply = dict(reply)
            out["reply"] = reply
            meta = reply.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
            else:
                meta = dict(meta)
            reply["metadata"] = meta
            focus = meta.get("coach_focus") or meta.get("coachFocus")
            if not isinstance(focus, dict):
                focus = {}
            else:
                focus = dict(focus)
            meta["coach_focus"] = focus
            _stamp_mapping(focus)

    if recovered_leftover:
        snapshot = out.get("snapshot")
        if isinstance(snapshot, dict):
            snapshot = dict(snapshot)
            out["snapshot"] = snapshot
            status = snapshot.get("plan_runtime_status") or snapshot.get("planRuntimeStatus")
            if not isinstance(status, dict):
                status = {}
            else:
                status = dict(status)
            snapshot["plan_runtime_status"] = status
            status["recovered"] = True

    return out


