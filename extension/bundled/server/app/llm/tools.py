"""Trainer coach tool registry.

This module turns Trainer's existing services (memory, planner, training cards,
resources, evaluator) into first-class **tools** the LLM can call inside an
agent loop. Each tool is described by a JSON Schema (so we can format it for
OpenAI / Anthropic / Gemini protocols) and a handler that executes against the
shared :class:`~app.api.runtime.TrainerRuntime` instance.

Design goals:

* **Coach-first**: tools surface evidence, propose plans, generate cards. They
  do **not** edit user code; that stays the learner's job.
* **Read-mostly with audit-friendly writes**: every write tool returns the
  delta it persisted so the agent loop can describe it back to the learner.
* **Resilient**: handlers convert exceptions into structured error payloads so
  one failing tool never aborts the loop.
* **Schema-driven**: each tool publishes a JSON Schema usable for
  ``response_format`` / ``tools=`` injection.

The registry stays focused: gather evidence, work the managed resource sandbox,
and commit explicit plan/library writes — never the learner's project code.
"""

from __future__ import annotations

import fnmatch
import inspect
import ipaddress
import json
import logging
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, cast
from urllib.parse import urlsplit
from uuid import uuid4

if TYPE_CHECKING:
    from ..core.models import ResponseLanguage

from ..core.models import (
    LearningPlan,
    PlanStage,
    ResourceIndexRequest,
    ResourceUploadRequest,
    SandboxBatchRenameRequest,
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxPreviewRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxWriteRequest,
)

logger = logging.getLogger("trainer.llm.tools")

# Learning OS fail-closed: coach agent must never silently write user business code.
# These names stay unregistered and are always denied even if hallucinated or re-added.
PROJECT_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {"write_file", "apply_patch", "edit_file"}
)

JsonSchema = dict[str, Any]
ToolHandler = Callable[["ToolContext", dict[str, Any]], Any]


@dataclass
class ToolContext:
    """Runtime context handed to every tool invocation.

    ``runtime`` is the live :class:`TrainerRuntime` (typed loosely to avoid an
    import cycle). ``workspace_id`` / ``session_id`` scope side effects.
    """

    runtime: Any
    workspace_id: str
    session_id: str | None = None
    profile: Any = None
    response_language: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    """A single LLM-callable tool."""

    name: str
    description: str
    parameters: JsonSchema
    handler: ToolHandler
    coach_only: bool = False
    """If True, this tool may only run when the learner has explicitly opted in
    (e.g. coach mode, not a hands-off run). The agent loop is responsible for
    enforcing this."""

    def schema_for(self, protocol: str) -> dict[str, Any]:
        """Return the tool definition formatted for the requested protocol."""
        if protocol in {"openai_chat_completions", "openai_chat_completions_compatible"}:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameters,
                },
            }
        if protocol == "openai_responses":
            return {
                "type": "function",
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        if protocol == "anthropic_messages":
            return {
                "name": self.name,
                "description": self.description,
                "input_schema": self.parameters,
            }
        if protocol == "gemini_generate_content":
            return {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        # Fallback: OpenAI chat shape works for most compatible providers.
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Container of available tools, keyed by name."""

    def __init__(self, tools: Iterable[ToolDefinition] | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for tool in tools or ():
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def as_protocol_schemas(
        self,
        protocol: str,
        *,
        allow_coach_only: bool = False,
        allowed_tool_names: Iterable[str] | None = None,
        denied_tool_names: Iterable[str] | None = None,
        explicit_training_card_request: bool = False,
        formal_plan_mutation: bool = False,
        explicit_learning_note_request: bool = False,
        explicit_resource_import: bool = False,
        explicit_resource_organize: bool = False,
        live_formal_plan_for_task_mint: bool = False,
    ) -> list[dict[str, Any]]:
        allowed = _tool_name_allowlist(allowed_tool_names)
        denied = _tool_name_allowlist(denied_tool_names) or set()
        # Learning OS: never expose project/business-code writers to the coach agent.
        denied.update(PROJECT_WRITE_TOOL_NAMES)
        # Composer chat / ReAct never mints; POST /training/generate-card binds ids.
        denied.add("generate_training_card")
        _ = explicit_training_card_request
        if formal_plan_mutation is not True:
            denied.add("save_formal_plan")
        if explicit_learning_note_request is not True:
            denied.add("record_learning_note")
        if explicit_resource_import is not True:
            denied.add("import_resource_url")
        if explicit_resource_organize is not True:
            denied.add("organize_resources")
        if live_formal_plan_for_task_mint is not True:
            denied.add("specify_task")
            denied.add("next_task")
        return [
            tool.schema_for(protocol)
            for tool in self._tools.values()
            if (allow_coach_only or not tool.coach_only)
            and (allowed is None or tool.name in allowed)
            and tool.name not in denied
        ]

    async def invoke(
        self,
        context: ToolContext,
        name: str,
        arguments: dict[str, Any] | str | None,
    ) -> dict[str, Any]:
        if name in PROJECT_WRITE_TOOL_NAMES:
            return {
                "ok": False,
                "error": "tool_not_available",
                "detail": (
                    "Coach tools must not silently write learner project or business code."
                ),
            }
        allowed = _tool_name_allowlist(context.extra.get("allowed_tool_names"))
        if allowed is not None and name not in allowed:
            return {
                "ok": False,
                "error": "tool_not_available",
                "detail": "This tool is not available for the current coaching turn.",
            }
        denied = _tool_name_allowlist(context.extra.get("denied_tool_names")) or set()
        denied.update(PROJECT_WRITE_TOOL_NAMES)
        if name == "generate_training_card" and not _explicit_training_card_request_allowed(context):
            return {
                "ok": False,
                "error": "explicit_training_card_request_required",
                "detail": (
                    "generate_training_card is only available when the learner "
                    "explicitly asked to create or generate a training card."
                ),
            }
        if name in {"specify_task", "next_task"} and not _task_mint_tool_allowed(context):
            return {
                "ok": False,
                "error": "live_formal_plan_required",
                "detail": (
                    f"{name} requires a live-bound formal plan and must not invent "
                    "a TaskSpec, second plan, or training card."
                ),
            }
        if name == "save_formal_plan" and not _formal_plan_mutation_allowed(context):
            return {
                "ok": False,
                "error": "formal_plan_mutation_required",
                "detail": "This write is only available during an explicit formal plan turn.",
            }
        if name == "import_resource_url" and not _resource_url_import_allowed(context):
            return {
                "ok": False,
                "error": "resource_import_not_allowed",
                "detail": (
                    "URL import is only available for an explicit Resources turn with "
                    "resource_composer_intent.mode=download."
                ),
            }
        if name == "organize_resources" and not _resource_organize_allowed(context):
            return {
                "ok": False,
                "error": "resource_organization_not_allowed",
                "detail": (
                    "Resource organization is only available for an explicit Resources turn "
                    "with resource_composer_intent.mode=organize."
                ),
            }
        if name in denied:
            return {
                "ok": False,
                "error": "tool_not_available",
                "detail": "This tool is not available for the current coaching turn.",
            }
        tool = self._tools.get(name)
        if tool is None:
            return {
                "ok": False,
                "error": "unknown_tool",
                "detail": f"Tool {name!r} is not registered.",
                "available": list(self._tools.keys()),
            }
        if tool.coach_only and not _coach_only_tools_allowed(context):
            return {
                "ok": False,
                "error": "coach_only_tool_not_allowed",
                "detail": (
                    f"Tool {name!r} changes coach memory or training state and is only "
                    "available in an explicit coach-enabled turn."
                ),
            }
        if name == "record_learning_note" and not _explicit_learning_note_request_allowed(context):
            return {
                "ok": False,
                "error": "explicit_learning_note_request_required",
                "detail": (
                    "record_learning_note is only available when the learner "
                    "explicitly asked to record or save a learning note."
                ),
            }
        parsed_arguments = _coerce_arguments(arguments)
        from .harness import (
            lookup_sandbox_operation,
            sandbox_operation_key,
            store_sandbox_operation,
        )

        operation_key = sandbox_operation_key(context.workspace_id, name, parsed_arguments)
        cached = lookup_sandbox_operation(context.runtime, operation_key)
        if cached is not None:
            replayed = dict(cached)
            replayed["replayed"] = True
            replayed.setdefault("ok", True)
            return replayed
        try:
            result = tool.handler(context, parsed_arguments)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                result = {"ok": True, "value": result}
            else:
                result = dict(result)
                result.setdefault("ok", True)
            store_sandbox_operation(context.runtime, operation_key, result)
            return result
        except Exception as exc:  # pragma: no cover - belt and braces
            logger.exception("tool_invocation_failed", extra={"tool": name})
            return {
                "ok": False,
                "error": exc.__class__.__name__,
                "detail": str(exc),
            }


def _tool_name_allowlist(value: object) -> set[str] | None:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return None
    return {item.strip() for item in value if isinstance(item, str) and item.strip()}


def _coach_only_tools_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("allow_coach_only_tools") is True


def _explicit_training_card_request_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    if extra.get("explicit_training_card_request") is True:
        return True
    from ..training.card_request import message_requests_explicit_training_card

    return message_requests_explicit_training_card(extra.get("learner_message"))


def _formal_plan_mutation_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("formal_plan_mutation") is True


def _task_mint_tool_allowed(context: ToolContext) -> bool:
    """Fail-closed: same live-plan identity as HTTP /task/next and /task/specify."""
    extra = context.extra if isinstance(context.extra, dict) else {}
    if extra.get("pressure_blocks_live_object_mint") is True:
        return False
    if extra.get("streak_blocks_live_object_mint") is True:
        return False
    if extra.get("closed_loop_return_blocks_task_mint") is True:
        return False
    live_plan = _live_formal_plan_for_task_mint(context)
    return live_plan is not None


def _live_formal_plan_for_task_mint(context: ToolContext) -> Any | None:
    leftover_plan, leftover_runtime, _leftover_task = _leftover_training_persist_identity(context)
    if leftover_plan is None or not leftover_runtime:
        return None
    from ..memory.workspace_recovery import leftover_formal_plan_is_live_for_fill

    if not leftover_formal_plan_is_live_for_fill(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
    ):
        return None
    return leftover_plan


def _persist_minted_task_on_sessions(context: ToolContext, task: Any, live_plan: Any) -> None:
    runtime = context.runtime
    if runtime is None:
        return
    workspace_id = context.workspace_id
    from ..memory.workspace_recovery import stamp_produced_workspace_record

    stamped_task = stamp_produced_workspace_record(task, workspace_id)
    stamped_plan = stamp_produced_workspace_record(live_plan, workspace_id)
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is not None:
        persist = getattr(memory_service, "persist_turn_context_pressure", None)
        if callable(persist):
            persist(workspace_id, current_task=stamped_task)
    for session_state in getattr(runtime, "sessions", {}).values():
        if getattr(session_state, "workspace_id", None) != workspace_id:
            continue
        session_state.snapshot.current_task = stamped_task
        if session_state.snapshot.plan is None:
            session_state.snapshot.plan = stamped_plan.model_copy(deep=True) if hasattr(stamped_plan, "model_copy") else stamped_plan
        save = getattr(runtime, "save_session_state", None)
        if callable(save):
            save(session_state.session_id)


def _explicit_learning_note_request_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    if extra.get("explicit_learning_note_request") is True:
        return True
    from ..memory.note_request import message_requests_explicit_learning_note

    return message_requests_explicit_learning_note(extra.get("learner_message"))


def resource_write_explicitly_requested(extra: dict[str, Any] | None, *, mode: str) -> bool:
    payload = extra if isinstance(extra, dict) else {}
    active_view = str(payload.get("active_view") or "").strip().lower()
    intent = payload.get("resource_composer_intent")
    model_dump = getattr(intent, "model_dump", None)
    if callable(model_dump):
        try:
            intent = model_dump()
        except Exception:
            intent = None
    if not isinstance(intent, dict):
        return False
    intent_mode = str(intent.get("mode") or "").strip().lower()
    if intent_mode != mode:
        return False
    return active_view == "resources" or payload.get("library_sandbox_work") is True


def _coerce_arguments(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_arguments": text}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw_arguments": parsed}
    return {"_raw_arguments": arguments}


# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------


def _string(prop_description: str, *, default: Any = None) -> JsonSchema:
    schema: JsonSchema = {"type": "string", "description": prop_description}
    if default is not None:
        schema["default"] = default
    return schema


def _enum(prop_description: str, values: list[str]) -> JsonSchema:
    return {"type": "string", "description": prop_description, "enum": values}


def _string_array(prop_description: str) -> JsonSchema:
    return {
        "type": "array",
        "description": prop_description,
        "items": {"type": "string"},
    }


def _resolve_workspace_root(context: ToolContext) -> Path | None:
    runtime = context.runtime
    if runtime is None:
        return None
    workspace_path = None
    try:
        workspace_path = runtime.resolve_workspace_path(context.workspace_id)
    except Exception:
        workspace_path = None
    if workspace_path is None:
        return None
    raw = str(workspace_path).strip()
    if not raw or "://" in raw:
        return None
    try:
        root = Path(raw).expanduser().resolve()
    except Exception:
        return None
    if not root.exists() or not root.is_dir():
        return None
    return root


def _safe_path_under(root: Path | None, candidate: str) -> Path | None:
    if not candidate:
        return None
    try:
        target = Path(candidate).expanduser()
    except Exception:
        return None
    if not target.is_absolute() and root is not None:
        target = root / target
    try:
        target = target.resolve()
    except Exception:
        return None
    if root is None:
        return target
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def _workspace_file_snapshot(context: ToolContext) -> dict[str, Any]:
    extra = context.extra if isinstance(context.extra, dict) else {}
    snapshot = extra.get("workspace_file_snapshot")
    payload = dict(snapshot) if isinstance(snapshot, dict) else {}
    contents = payload.get("contents")
    fulfill = getattr(context.runtime, "fulfill_requested_workspace_files", None) if context.runtime is not None else None
    if callable(fulfill) and isinstance(contents, dict):
        fulfill(context.workspace_id, contents.keys())
    return payload


def _normalize_workspace_relpath(path_raw: str) -> str:
    return str(path_raw or "").replace("\\", "/").lstrip("./")


def _snapshot_file_record(context: ToolContext, path_raw: str) -> dict[str, Any] | None:
    wanted = _normalize_workspace_relpath(path_raw)
    if not wanted:
        return None
    snapshot = _workspace_file_snapshot(context)
    contents = snapshot.get("contents")
    if isinstance(contents, dict):
        for key, record in contents.items():
            relative = _normalize_workspace_relpath(str(key))
            if relative == wanted or relative.endswith("/" + wanted) or wanted.endswith("/" + relative):
                if isinstance(record, dict) and str(record.get("content") or ""):
                    return {
                        "path": relative,
                        "content": str(record.get("content") or ""),
                        "language_id": record.get("language_id"),
                    }
    current = extra_current_file(context)
    if current is not None:
        current_path = _normalize_workspace_relpath(str(current.get("path") or ""))
        if current_path.endswith("/" + wanted) or current_path == wanted or wanted.endswith(current_path.split("/")[-1]):
            content = str(current.get("content") or current.get("content_excerpt") or "")
            if content:
                return {"path": current_path or wanted, "content": content, "language_id": current.get("language_id")}
        related = current.get("related_files")
        if isinstance(related, list):
            for item in related:
                if not isinstance(item, dict):
                    continue
                rel = _normalize_workspace_relpath(str(item.get("path") or ""))
                excerpt = str(item.get("excerpt") or "")
                if excerpt and (rel == wanted or rel.endswith("/" + wanted) or wanted.endswith(rel.split("/")[-1])):
                    return {"path": rel or wanted, "content": excerpt}
    return None


def extra_current_file(context: ToolContext) -> dict[str, Any] | None:
    extra = context.extra if isinstance(context.extra, dict) else {}
    current = extra.get("current_file")
    return dict(current) if isinstance(current, dict) else None


def _snapshot_file_list(context: ToolContext) -> list[dict[str, Any]]:
    snapshot = _workspace_file_snapshot(context)
    files = snapshot.get("files")
    items: list[dict[str, Any]] = []
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                items.append(
                    {
                        "path": _normalize_workspace_relpath(str(item.get("path"))),
                        "is_dir": False,
                        "size": item.get("size"),
                    }
                )
    contents = snapshot.get("contents")
    if isinstance(contents, dict):
        existing = {str(item.get("path") or "") for item in items}
        for key in contents:
            relative = _normalize_workspace_relpath(str(key))
            if relative and relative not in existing:
                items.append({"path": relative, "is_dir": False})
                existing.add(relative)
    if items:
        return items
    current = extra_current_file(context)
    if current is None:
        return []
    path = _normalize_workspace_relpath(str(current.get("path") or ""))
    if path:
        items.append({"path": path, "is_dir": False})
    related = current.get("related_files")
    if isinstance(related, list):
        for item in related:
            if not isinstance(item, dict):
                continue
            rel = _normalize_workspace_relpath(str(item.get("path") or ""))
            if rel:
                items.append({"path": rel, "is_dir": False})
    return items


def _snapshot_path_matches(path_raw: str, pattern: str) -> bool:
    relative = _normalize_workspace_relpath(path_raw)
    pat = str(pattern or "**/*").replace("\\", "/").strip() or "**/*"
    if pat in {"*", "**", "**/*", "."}:
        return True
    if fnmatch.fnmatch(relative, pat):
        return True
    if pat.startswith("**/") and fnmatch.fnmatch(relative, pat[3:]):
        return True
    return fnmatch.fnmatch(Path(relative).name, pat)


def _snapshot_file_listed(context: ToolContext, path_raw: str) -> bool:
    wanted = _normalize_workspace_relpath(path_raw)
    if not wanted:
        return False
    for item in _snapshot_file_list(context):
        relative = _normalize_workspace_relpath(str(item.get("path") or ""))
        if relative == wanted or relative.endswith("/" + wanted) or wanted.endswith("/" + relative):
            return True
    return False


# --- search_resources ---------------------------------------------------


async def _handle_search_resources(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    runtime = context.runtime
    query = str(args.get("query") or "").strip()
    mode = _normalize_search_mode(args.get("mode") or args.get("search_mode"))
    limit_raw = args.get("limit", 5)
    try:
        limit = max(1, min(int(limit_raw), 12))
    except Exception:
        limit = 5
    if not query:
        return {"ok": False, "error": "missing_query", "detail": "search_resources requires a non-empty query."}
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": (
                "The resource library is not attached to this run, so no local "
                "resource citation can be used for this answer."
            ),
        }
    try:
        project_scope = str(args.get("project_scope") or "").strip() or None
        trust_state = str(args.get("trust_state") or "").strip() or None
        file_type = str(args.get("file_type") or "").strip() or None
        source_type = str(args.get("source_type") or "").strip() or None
        kind = str(args.get("kind") or "").strip() or None
        index_state = str(args.get("index_state") or "").strip() or None
        internal_limit = _internal_search_limit(mode, limit)

        # Most resource services expose either search() or search_resources()
        # and return a structured search response object, not a raw list.
        if hasattr(resource_service, "search"):
            search_result = resource_service.search(
                workspace_id=context.workspace_id,
                query=query,
                top_k=internal_limit,
                project_scope=project_scope,
                trust_state=trust_state,
                file_type=file_type,
                source_type=source_type,
                kind=kind,
                index_state=index_state,
            )
        elif hasattr(resource_service, "search_resources"):
            search_result = resource_service.search_resources(
                workspace_id=context.workspace_id,
                query=query,
                top_k=internal_limit,
                project_scope=project_scope,
                trust_state=trust_state,
                file_type=file_type,
                source_type=source_type,
                kind=kind,
                index_state=index_state,
            )
        else:
            return {
                "ok": False,
                "error": "unsupported",
                "detail": "Resource service does not expose a search() method.",
            }
        if inspect.isawaitable(search_result):
            search_result = await search_result
    except Exception as exc:  # pragma: no cover - exercised in integration
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}

    normalized = _normalize_search_response(search_result, fallback_query=query)
    visible_hits = _apply_search_mode(normalized["hits"], mode=mode)
    verification_ready_count = sum(1 for hit in normalized["hits"] if _is_verification_ready_hit(hit))
    verification_warning = mode == "verify" and verification_ready_count == 0 and bool(normalized["hits"])
    summary = _build_search_summary(
        query=query,
        mode=mode,
        returned_count=min(len(visible_hits), limit),
        total=int(normalized["total"]),
        verification_ready_count=verification_ready_count,
        verification_warning=verification_warning,
    )
    return {
        "ok": True,
        "query": normalized["query"] or query,
        "mode": mode,
        "total": int(normalized["total"]),
        "ranking_strategy": normalized["ranking_strategy"],
        "filters": normalized["filters"],
        "verification_ready_count": verification_ready_count,
        "verification_warning": verification_warning,
        "summary": summary,
        "hits": visible_hits[:limit],
    }


# --- import_resource_url -------------------------------------------------


def _resource_url_import_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    return (
        extra.get("explicit_resource_import") is True
        or extra.get("library_sandbox_work") is True
        or resource_write_explicitly_requested(extra, mode="download")
    )


def _validate_public_http_url(value: Any) -> tuple[str | None, str | None]:
    url = str(value or "").strip()
    if not url:
        return None, "import_resource_url requires a non-empty url."
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None, "URL is invalid."
    if parsed.scheme.lower() not in {"http", "https"}:
        return None, "Only http and https URLs are allowed."
    if parsed.username is not None or parsed.password is not None:
        return None, "URL userinfo is not allowed."
    hostname = (parsed.hostname or "").strip().rstrip(".")
    if not hostname:
        return None, "URL host is missing."
    try:
        port = parsed.port
    except ValueError:
        return None, "URL port is invalid."
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if port is not None and port != default_port:
        return None, "Only standard HTTP and HTTPS ports are allowed."
    if hostname.casefold() in {"localhost", "localhost.localdomain"}:
        return None, "Only public URL hosts are allowed."
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None, "Only public URL hosts are allowed."
    return url, None


def _resource_import_name(url: str, requested_name: Any) -> str:
    name = str(requested_name or "").strip()
    if name:
        return name[:200]
    parsed = urlsplit(url)
    path_name = Path(parsed.path.rstrip("/")).name.strip()
    return (path_name or parsed.hostname or "Imported URL")[:200]


def _resource_model_payload(resource: Any) -> dict[str, Any]:
    if hasattr(resource, "model_dump") and callable(resource.model_dump):
        try:
            payload = resource.model_dump(mode="json")
        except TypeError:
            payload = resource.model_dump()
        return payload if isinstance(payload, dict) else {}
    if is_dataclass(resource) and not isinstance(resource, type):
        try:
            payload = asdict(cast(Any, resource))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    return dict(resource) if isinstance(resource, dict) else {}


def _resource_provenance(resource_service: Any, resource: Any) -> dict[str, Any]:
    resource_id = str(getattr(resource, "id", "") or "")
    registry = getattr(resource_service, "registry", None)
    if registry is None or not resource_id:
        return {}
    try:
        registered = registry.get(resource_id)
    except Exception:
        return {}
    metadata = getattr(registered, "metadata", None)
    provenance = metadata.get("source_provenance") if isinstance(metadata, dict) else None
    return dict(provenance) if isinstance(provenance, dict) else {}


async def _handle_import_resource_url(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not _resource_url_import_allowed(context):
        return {
            "ok": False,
            "error": "resource_import_not_allowed",
            "detail": (
                "URL import is only available for an explicit Resources turn with "
                "resource_composer_intent.mode=download."
            ),
        }

    url, validation_error = _validate_public_http_url(args.get("url"))
    if validation_error:
        return {
            "ok": False,
            "error": "invalid_url" if args.get("url") else "missing_url",
            "detail": validation_error,
        }
    assert url is not None

    resource_service = getattr(context.runtime, "resource_service", None)
    if resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The resource library is not attached to this run.",
        }

    raw_tags = args.get("tags")
    tags = cast(list[Any], raw_tags) if isinstance(raw_tags, list) else []
    request = ResourceUploadRequest(
        session_id=context.session_id,
        workspace_id=context.workspace_id,
        kind="url",
        name=_resource_import_name(url, args.get("name")),
        source=url,
        source_type="url",
        tags=[str(tag).strip() for tag in tags if str(tag).strip()][:20],
    )
    try:
        uploaded = resource_service.upload(context.workspace_id, request)
        if inspect.isawaitable(uploaded):
            uploaded = await uploaded
    except Exception as exc:
        return {
            "ok": False,
            "error": "resource_upload_failed",
            "detail": str(exc),
            "source": {"requested_url": url},
        }

    try:
        indexed = resource_service.index(
            context.workspace_id,
            ResourceIndexRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                resource_id=str(getattr(uploaded, "id", "") or ""),
                enable_network=True,
            ),
        )
        if inspect.isawaitable(indexed):
            indexed = await indexed
    except Exception as exc:
        uploaded_payload = _resource_model_payload(uploaded)
        return {
            "ok": False,
            "error": "resource_index_failed",
            "detail": str(exc),
            "resource_id": uploaded_payload.get("id"),
            "status": "index_failed",
            "source": {
                "requested_url": url,
                "canonical_url": uploaded_payload.get("canonical_source") or url,
            },
            "resource": uploaded_payload,
        }

    postprocessing: dict[str, Any] = {}
    postprocess_indexed_resource = getattr(context.runtime, "postprocess_indexed_resource", None)
    if callable(postprocess_indexed_resource):
        try:
            postprocessed = postprocess_indexed_resource(
                context.workspace_id,
                indexed,
                refresh_sessions=True,
            )
            if inspect.isawaitable(postprocessed):
                postprocessed = await postprocessed
            if isinstance(postprocessed, tuple) and len(postprocessed) == 2:
                indexed, raw_summary = postprocessed
                if isinstance(raw_summary, dict):
                    postprocessing = dict(raw_summary)
            elif postprocessed is not None:
                indexed = postprocessed
        except Exception as exc:
            payload = _resource_model_payload(indexed)
            return {
                "ok": False,
                "error": "resource_postprocess_failed",
                "detail": str(exc),
                "resource_id": payload.get("id"),
                "status": str(payload.get("index_status") or payload.get("parse_status") or "unknown"),
                "resource": payload,
            }

    payload = _resource_model_payload(indexed)
    provenance = _resource_provenance(resource_service, indexed)
    index_status = str(payload.get("index_status") or "").strip().lower()
    parse_status = str(payload.get("parse_status") or "").strip().lower()
    succeeded = index_status == "indexed" and parse_status == "parsed"
    result: dict[str, Any] = {
        "ok": succeeded,
        "resource_id": payload.get("id"),
        "status": index_status or parse_status or "unknown",
        "source": {
            "requested_url": payload.get("source") or url,
            "canonical_url": payload.get("canonical_source") or url,
            "fetched_at": payload.get("fetched_at"),
            "provenance": provenance,
        },
        "resource": payload,
        "warnings": list(payload.get("warnings") or []),
        "quality_flags": list(payload.get("quality_flags") or []),
        "postprocessing": postprocessing,
    }
    if not succeeded:
        result["error"] = "resource_import_failed"
        result["detail"] = (
            "The URL was registered, but controlled ingestion did not produce an indexed resource."
        )
    return result


# --- organize_resources --------------------------------------------------


def _resource_organize_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    return (
        extra.get("explicit_resource_organize") is True
        or extra.get("library_sandbox_work") is True
        or resource_write_explicitly_requested(extra, mode="organize")
    )


def _resource_organization_host_confirmed(context: ToolContext) -> bool:
    """Host/user attestation only — never trust tool-arg self-attestation."""

    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("resource_organization_confirmed") is True


def _resource_organization_autonomous(context: ToolContext) -> bool:
    """Resources/library turns let Trainer commit sandbox organization itself.

    The host already selected the Resources lane. Tool-arg `confirmed=true`
    is still ignored; this flag is stamped by the sidecar, not the model.
    """

    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("library_sandbox_work") is True


def _resource_organization_pending_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_pending", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_pending = store
    except Exception:
        pass
    return store


def _resource_organization_cancel_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_cancel_requested", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_cancel_requested = store
    except Exception:
        pass
    return store


def _resource_organization_in_flight_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_in_flight", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_in_flight = store
    except Exception:
        pass
    return store


def _resource_organization_committed_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_last_committed", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_last_committed = store
    except Exception:
        pass
    return store


def _mark_resource_organization_cancel_requested(runtime: Any, workspace_id: str) -> None:
    _resource_organization_cancel_store(runtime)[workspace_id] = True


def _resource_organization_cancel_requested(runtime: Any, workspace_id: str) -> bool:
    store = getattr(runtime, "resource_organization_cancel_requested", None)
    return isinstance(store, dict) and bool(store.get(workspace_id))


def _take_resource_organization_cancel_requested(runtime: Any, workspace_id: str) -> bool:
    store = getattr(runtime, "resource_organization_cancel_requested", None)
    if not isinstance(store, dict) or workspace_id not in store:
        return False
    return bool(store.pop(workspace_id, None))


def _clear_resource_organization_cancel_requested(runtime: Any, workspace_id: str) -> None:
    store = getattr(runtime, "resource_organization_cancel_requested", None)
    if isinstance(store, dict):
        store.pop(workspace_id, None)


def _mark_resource_organization_in_flight(runtime: Any, workspace_id: str) -> None:
    _resource_organization_in_flight_store(runtime)[workspace_id] = True


def _clear_resource_organization_in_flight(runtime: Any, workspace_id: str) -> None:
    store = getattr(runtime, "resource_organization_in_flight", None)
    if isinstance(store, dict):
        store.pop(workspace_id, None)


def _has_resource_organization_in_flight(runtime: Any, workspace_id: str) -> bool:
    store = getattr(runtime, "resource_organization_in_flight", None)
    return isinstance(store, dict) and bool(store.get(workspace_id))


def _stamp_resource_organization_committed(runtime: Any, workspace_id: str) -> None:
    _resource_organization_committed_store(runtime)[workspace_id] = True


def _clear_resource_organization_committed(runtime: Any, workspace_id: str) -> None:
    store = getattr(runtime, "resource_organization_last_committed", None)
    if isinstance(store, dict):
        store.pop(workspace_id, None)


def _has_resource_organization_committed(runtime: Any, workspace_id: str) -> bool:
    store = getattr(runtime, "resource_organization_last_committed", None)
    return isinstance(store, dict) and bool(store.get(workspace_id))


def cancel_resource_organization_pending(runtime: Any, workspace_id: str) -> dict[str, Any]:
    """Host cancel: clear pending + latch, or honest failure when write already committed."""

    had_pending = _has_resource_organization_pending(runtime, workspace_id)
    in_flight = _has_resource_organization_in_flight(runtime, workspace_id)
    already_committed = (
        not had_pending
        and not in_flight
        and _has_resource_organization_committed(runtime, workspace_id)
    )
    _clear_resource_organization_pending(runtime, workspace_id)
    if already_committed:
        # Completed sandbox write still wins — do not restore pending or latch poison.
        return {
            "ok": False,
            "cleared": False,
            "cancelled": False,
            "already_committed": True,
            "cancel_latched": False,
            "error": "resource_organization_already_committed",
        }
    _mark_resource_organization_cancel_requested(runtime, workspace_id)
    return {
        "ok": True,
        "cleared": had_pending,
        "cancelled": True,
        "already_committed": False,
        "cancel_latched": True,
    }


def _record_resource_organization_pending(
    runtime: Any, workspace_id: str, operations: list[dict[str, Any]]
) -> None:
    # Fresh proposal clears any prior cancel latch from a raced in-flight confirm.
    _clear_resource_organization_cancel_requested(runtime, workspace_id)
    _clear_resource_organization_committed(runtime, workspace_id)
    store = _resource_organization_pending_store(runtime)
    store[workspace_id] = {"operations": list(operations)}


def _has_resource_organization_pending(runtime: Any, workspace_id: str) -> bool:
    store = getattr(runtime, "resource_organization_pending", None)
    return isinstance(store, dict) and workspace_id in store


def _clear_resource_organization_pending(runtime: Any, workspace_id: str) -> None:
    store = getattr(runtime, "resource_organization_pending", None)
    if isinstance(store, dict):
        store.pop(workspace_id, None)


def _consume_resource_organization_pending(
    runtime: Any, workspace_id: str
) -> dict[str, Any] | None:
    """Atomically take pending for commit. Cancel wins if it popped first."""

    store = getattr(runtime, "resource_organization_pending", None)
    if not isinstance(store, dict) or workspace_id not in store:
        return None
    entry = store.pop(workspace_id, None)
    if isinstance(entry, dict):
        _mark_resource_organization_in_flight(runtime, workspace_id)
        return entry
    return None


def _safe_sandbox_relative_path(value: Any, *, field_name: str) -> str:
    """Normalize a path before handing it to SandboxService's boundary checks."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw:
        raise ValueError(f"{field_name} must be a non-empty sandbox-relative path.")
    # Organization is intentionally relative to the managed sandbox. Absolute
    # paths and traversal are rejected before the service sees them.
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError(f"{field_name} must stay relative to the managed sandbox.")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"{field_name} must stay relative to the managed sandbox.")
    return "/".join(parts)


def _resource_for_workspace(runtime: Any, workspace_id: str, resource_id: str) -> Any | None:
    repository = getattr(runtime, "repository", None)
    list_resources = getattr(repository, "list_resources", None)
    if not callable(list_resources):
        return None
    try:
        for resource in list_resources(workspace_id):
            if str(getattr(resource, "id", "") or "") == resource_id:
                return resource
    except Exception:
        return None
    return None


def _normalize_sandbox_path_key(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()


def _match_resource_by_sandbox_path(
    runtime: Any,
    workspace_id: str,
    source_relative: str,
) -> Any | None:
    """Bind a path-only organize op to the library record that currently owns that sandbox file."""

    wanted_relative = _normalize_sandbox_path_key(source_relative)
    if not wanted_relative:
        return None
    repository = getattr(runtime, "repository", None)
    list_resources = getattr(repository, "list_resources", None)
    if not callable(list_resources):
        return None
    sandbox_service = getattr(runtime, "sandbox_service", None)
    wanted_absolute = wanted_relative
    sandbox_root: Path | None = None
    if sandbox_service is not None:
        try:
            sandbox_root = Path(sandbox_service.ensure_operation_root(workspace_id)).resolve()
            wanted_absolute = _normalize_sandbox_path_key(str((sandbox_root / source_relative).resolve()))
        except Exception:
            sandbox_root = None
    try:
        resources = list_resources(workspace_id)
    except Exception:
        return None
    matches: list[Any] = []
    for resource in resources or []:
        sandbox_path = str(getattr(resource, "sandbox_path", "") or "").strip()
        if not sandbox_path:
            continue
        keys = {_normalize_sandbox_path_key(sandbox_path)}
        try:
            keys.add(_normalize_sandbox_path_key(str(Path(sandbox_path).resolve())))
        except Exception:
            pass
        if sandbox_root is not None:
            try:
                resolved = Path(sandbox_path)
                if not resolved.is_absolute():
                    resolved = sandbox_root / sandbox_path
                resolved = resolved.resolve()
                keys.add(_normalize_sandbox_path_key(str(resolved)))
                keys.add(_normalize_sandbox_path_key(resolved.relative_to(sandbox_root).as_posix()))
            except Exception:
                pass
        if wanted_relative in keys or wanted_absolute in keys:
            matches.append(resource)
    if len(matches) == 1:
        return matches[0]
    return None


def _collect_organization_resource_updates(
    context: ToolContext,
    operations: list[dict[str, Any]],
) -> list[tuple[Any, str, str]]:
    updates: list[tuple[Any, str, str]] = []
    seen_ids: set[str] = set()
    for operation in operations:
        if operation.get("op") not in {"move", "rename"}:
            continue
        source = str(operation.get("source") or "")
        target = str(operation.get("target") or "")
        if not source or not target:
            continue
        resource_id = str(operation.get("resource_id") or "").strip()
        resource = (
            _resource_for_workspace(context.runtime, context.workspace_id, resource_id)
            if resource_id
            else None
        )
        if resource is None:
            resource = _match_resource_by_sandbox_path(
                context.runtime,
                context.workspace_id,
                source,
            )
        resource_key = str(getattr(resource, "id", "") or "").strip() if resource is not None else ""
        if resource is None or (resource_key and resource_key in seen_ids):
            continue
        if resource_key:
            seen_ids.add(resource_key)
        updates.append((resource, source, target))
    return updates


def _organization_operation_payload(raw: dict[str, Any], *, index: int) -> dict[str, Any]:
    operation = str(raw.get("op") or raw.get("operation") or raw.get("action") or "").strip().lower()
    if operation in {"move", "rename"}:
        source = raw.get("source") or raw.get("path")
        target = raw.get("target") or raw.get("new_path") or raw.get("newPath")
        return {
            "op": "move" if operation == "move" else "rename",
            "source": source,
            "target": target,
            "resource_id": str(raw.get("resource_id") or raw.get("resourceId") or "").strip(),
            "index": index,
        }
    if operation in {"mkdir", "make_directory", "create_folder", "create_directory"}:
        return {
            "op": "mkdir",
            "path": raw.get("path") or raw.get("target") or raw.get("new_path") or raw.get("newPath"),
            "index": index,
        }
    if operation in {"delete", "trash"}:
        return {
            "op": "delete",
            "path": raw.get("path") or raw.get("source"),
            "index": index,
        }
    if operation in {"restore", "undo_delete"}:
        return {
            "op": "restore",
            "path": raw.get("path") or raw.get("source"),
            "index": index,
        }
    raise ValueError("Supported organization operations are mkdir, move, and rename.")


def _organization_undo_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    undo: list[dict[str, Any]] = []
    for item in reversed(operations):
        op = item.get("op")
        if op in {"move", "rename"}:
            reverse = {
                "op": op,
                "source": item.get("target"),
                "target": item.get("source"),
            }
            if item.get("resource_id"):
                reverse["resource_id"] = item["resource_id"]
            undo.append(reverse)
        elif op == "mkdir":
            # The sandbox delete route moves the empty folder to Trash, so the
            # inverse remains recoverable instead of permanently deleting it.
            undo.append({"op": "delete", "path": item.get("path")})
        elif op == "delete":
            undo.append({"op": "restore", "path": item.get("path")})
    return undo


def _latest_trash_relative_path(sandbox_service: Any, workspace_id: str, original_path: str) -> str | None:
    """Find the managed Trash handle created for a just-deleted path."""

    try:
        root = sandbox_service.ensure_operation_root(workspace_id)
        trash_root = sandbox_service._trash_root_path(root)
        original_parts = tuple(Path(original_path).parts)
        candidates: list[Path] = []
        for candidate in trash_root.rglob(Path(original_path).name):
            relative = candidate.relative_to(trash_root)
            if len(relative.parts) > len(original_parts) and tuple(relative.parts[-len(original_parts) :]) == original_parts:
                candidates.append(candidate)
        if not candidates:
            return None
        selected = max(candidates, key=lambda item: item.stat().st_mtime_ns)
        return selected.relative_to(root).as_posix()
    except Exception:
        return None


def _organization_resource_path(
    context: ToolContext,
    operation: dict[str, Any],
) -> tuple[str, str, Any | None]:
    runtime = context.runtime
    resource_id = str(operation.get("resource_id") or "").strip()
    resource = _resource_for_workspace(runtime, context.workspace_id, resource_id) if resource_id else None
    source = operation.get("source")
    if resource_id and not source:
        if resource is None:
            raise ValueError(f"Resource {resource_id!r} was not found in the active workspace.")
        source = getattr(resource, "sandbox_path", None)
        if not source:
            raise ValueError(f"Resource {resource_id!r} has no sandbox artifact to organize.")
        sandbox_service = getattr(runtime, "sandbox_service", None)
        root = sandbox_service.ensure_operation_root(context.workspace_id) if sandbox_service is not None else None
        if root is not None:
            try:
                source = Path(str(source)).resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError as exc:
                raise ValueError(f"Resource {resource_id!r} is outside the managed sandbox.") from exc
    normalized_source = _safe_sandbox_relative_path(source, field_name="source")
    normalized_target = _safe_sandbox_relative_path(operation.get("target"), field_name="target")
    if resource is None:
        resource = _match_resource_by_sandbox_path(
            runtime,
            context.workspace_id,
            normalized_source,
        )
    return normalized_source, normalized_target, resource


async def _handle_organize_resources(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not _resource_organize_allowed(context):
        return {
            "ok": False,
            "error": "resource_organization_not_allowed",
            "detail": (
                "Resource organization is only available for an explicit Resources turn "
                "with resource_composer_intent.mode=organize."
            ),
        }

    runtime = context.runtime
    sandbox_service = getattr(runtime, "sandbox_service", None)
    if sandbox_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "The managed sandbox is not configured."}

    undo_id = str(args.get("undo_id") or "").strip()
    history = getattr(runtime, "resource_organization_history", {})
    if undo_id:
        stored = history.get(undo_id) if isinstance(history, dict) else None
        if not isinstance(stored, dict) or str(stored.get("workspace_id") or "") != context.workspace_id:
            return {"ok": False, "error": "unknown_undo_id", "detail": "The organization change is no longer available for undo."}
        raw_operations = stored.get("undo_operations")
        operations = raw_operations if isinstance(raw_operations, list) else []
    else:
        raw_operations = args.get("operations")
        if not isinstance(raw_operations, list) or not raw_operations:
            return {"ok": False, "error": "operations_required", "detail": "Provide at least one organization operation."}
        try:
            operations = [
                _organization_operation_payload(item, index=index)
                for index, item in enumerate(raw_operations[:20])
                if isinstance(item, dict)
            ]
        except ValueError as exc:
            return {"ok": False, "error": "invalid_operation", "detail": str(exc)}
        if not operations:
            return {"ok": False, "error": "operations_required", "detail": "Provide at least one organization operation."}

    normalized_operations: list[dict[str, Any]] = []
    try:
        for operation in operations:
            if operation.get("op") == "mkdir":
                operation = dict(operation)
                operation["path"] = _safe_sandbox_relative_path(operation.get("path"), field_name="path")
                normalized_operations.append(operation)
                continue
            if operation.get("op") == "delete":
                operation = dict(operation)
                operation["path"] = _safe_sandbox_relative_path(operation.get("path"), field_name="path")
                normalized_operations.append(operation)
                continue
            if operation.get("op") == "restore":
                operation = dict(operation)
                operation["path"] = _safe_sandbox_relative_path(operation.get("path"), field_name="path")
                normalized_operations.append(operation)
                continue
            source, target, resource = _organization_resource_path(context, operation)
            normalized = dict(operation)
            normalized["source"] = source
            normalized["target"] = target
            resource_id = str(getattr(resource, "id", "") or "").strip() if resource is not None else ""
            if resource_id:
                normalized["resource_id"] = resource_id
            normalized_operations.append(normalized)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_path", "detail": str(exc)}

    # Fail-closed: ignore args.confirmed — models can invent it. Host stamp or
    # an explicit Resources/library turn (library_sandbox_work) may mutate the
    # managed sandbox. Learner project files stay out of reach.
    host_confirmed = _resource_organization_host_confirmed(context)
    autonomous = _resource_organization_autonomous(context)
    if args.get("confirmed") is True and not host_confirmed and not autonomous:
        _record_resource_organization_pending(runtime, context.workspace_id, normalized_operations)
        return {
            "ok": False,
            "error": "host_confirmation_required",
            "detail": (
                "organize_resources cannot self-attest confirmation via tool args. "
                "The host must stamp resource_organization_confirmed after the learner reviews the proposal."
            ),
            "committed": False,
            "requires_confirmation": True,
            "operations": normalized_operations,
            "undo_operations": _organization_undo_operations(normalized_operations),
        }
    if not host_confirmed and not autonomous:
        _record_resource_organization_pending(runtime, context.workspace_id, normalized_operations)
        return {
            "ok": True,
            "committed": False,
            "requires_confirmation": True,
            "confirmation": (
                "Proposal only. Host/user confirmation is required before commit; "
                "do not resend with confirmed=true."
            ),
            "operations": normalized_operations,
            "undo_operations": _organization_undo_operations(normalized_operations),
        }

    # Stamp alone is insufficient: Direct API resourceOrganizationConfirmed without a
    # prior proposal must not commit. Consume pending atomically before any FS write so
    # cancel-while-confirm-in-flight cannot race a check-then-mutate commit. Undo exempt.
    # If FS work aborts after consume, restore pending so the proposal stays recoverable;
    # empty-pending second confirm / cancel stays fail-closed.
    # Cancel during/after consume sets a latch so abort must not resurrect pending.
    # Autonomous library turns commit the current op list: Trainer already owns
    # the managed sandbox on a Resources turn, so a leftover pending proposal
    # must not block or replace the live command.
    consumed_pending: dict[str, Any] | None = None
    if not undo_id and autonomous and not host_confirmed:
        _clear_resource_organization_pending(runtime, context.workspace_id)
    elif not undo_id:
        consumed_pending = _consume_resource_organization_pending(
            runtime, context.workspace_id
        )
        if consumed_pending is None:
            return {
                "ok": False,
                "error": "host_confirmation_required",
                "detail": (
                    "No pending organize_resources proposal for this workspace. "
                    "Propose first; the host must stamp resource_organization_confirmed after review."
                ),
                "committed": False,
                "requires_confirmation": True,
                "operations": normalized_operations,
                "undo_operations": _organization_undo_operations(normalized_operations),
            }
        pending_ops = consumed_pending.get("operations")
        if isinstance(pending_ops, list) and pending_ops:
            # Host confirmation commits the reviewed proposal, not a newly invented op list.
            normalized_operations = [dict(item) for item in pending_ops if isinstance(item, dict)]

    resource_updates = _collect_organization_resource_updates(context, normalized_operations)

    created_directories: list[str] = []
    try:
        if not undo_id and _resource_organization_cancel_requested(
            runtime, context.workspace_id
        ):
            raise RuntimeError("resource_organization_cancelled")
        for operation in normalized_operations:
            if operation.get("op") != "mkdir":
                continue
            path = str(operation["path"])
            sandbox_service.mkdir(
                context.workspace_id,
                SandboxMkdirRequest(
                    workspace_id=context.workspace_id,
                    path=path,
                    explicit_destructive_policy=True,
                ),
                resources=[],
                workspace_root_path=getattr(runtime, "resolve_workspace_path", lambda _workspace_id: None)(context.workspace_id),
            )
            created_directories.append(path)

        rename_items = [
            SandboxRenameRequest(path=str(item["source"]), new_path=str(item["target"]))
            for item in normalized_operations
            if item.get("op") in {"move", "rename"}
        ]
        batch_result: dict[str, Any] = {}
        if rename_items:
            batch_result = dict(
                sandbox_service.batch_rename(
                    context.workspace_id,
                    SandboxBatchRenameRequest(
                        workspace_id=context.workspace_id,
                        items=rename_items,
                        explicit_destructive_policy=True,
                    ),
                )
            )

        deleted_paths: list[str] = []
        restored_paths: list[str] = []
        deleted_trash_paths: dict[str, str] = {}
        for operation in normalized_operations:
            path = str(operation.get("path") or "")
            if operation.get("op") == "delete":
                sandbox_service.delete(
                    context.workspace_id,
                    SandboxDeleteRequest(
                        workspace_id=context.workspace_id,
                        path=path,
                        explicit_destructive_policy=True,
                    ),
                    resources=[],
                    workspace_root_path=getattr(runtime, "resolve_workspace_path", lambda _workspace_id: None)(context.workspace_id),
                )
                deleted_paths.append(path)
                trash_relative = _latest_trash_relative_path(sandbox_service, context.workspace_id, path)
                if trash_relative:
                    deleted_trash_paths[path] = trash_relative
            elif operation.get("op") == "restore":
                sandbox_service.restore(
                    context.workspace_id,
                    SandboxRestoreRequest(
                        workspace_id=context.workspace_id,
                        path=path,
                        explicit_destructive_policy=True,
                    ),
                    resources=[],
                    workspace_root_path=getattr(runtime, "resolve_workspace_path", lambda _workspace_id: None)(context.workspace_id),
                )
                restored_paths.append(path)

        repository = getattr(runtime, "repository", None)
        resource_service = getattr(runtime, "resource_service", None)
        sandbox_root = sandbox_service.ensure_operation_root(context.workspace_id)
        for resource, _source, target in resource_updates:
            absolute_target = str((Path(sandbox_root) / target).resolve())
            refresh = getattr(resource_service, "refresh_organized_resource", None) if resource_service is not None else None
            if callable(refresh):
                refresh(
                    context.workspace_id,
                    resource,
                    sandbox_path=absolute_target,
                )
                continue
            if repository is None or not hasattr(repository, "save_resource"):
                continue
            updated = resource.model_copy(
                update={
                    "sandbox_path": absolute_target,
                    "sandbox_dirty": False,
                }
            )
            repository.save_resource(context.workspace_id, updated)

        undo_operations = _organization_undo_operations(normalized_operations)
        for undo_operation in undo_operations:
            if undo_operation.get("op") != "restore":
                continue
            original_path = str(undo_operation.get("path") or "")
            undo_operation["path"] = deleted_trash_paths.get(original_path, original_path)
        if undo_id:
            if isinstance(history, dict):
                history.pop(undo_id, None)
            refresh_sessions = getattr(runtime, "refresh_workspace_sessions", None)
            sessions_refreshed = int(refresh_sessions(context.workspace_id) or 0) if callable(refresh_sessions) else 0
            return {
                "ok": True,
                "committed": True,
                "undone": True,
                "undo_id": undo_id,
                "operations": normalized_operations,
                "deleted_paths": deleted_paths,
                "restored_paths": restored_paths,
                "changes": batch_result.get("changes", []),
                "sessions_refreshed": sessions_refreshed,
            }
        history_id = f"org-{uuid4().hex}"
        if isinstance(history, dict):
            history[history_id] = {
                "workspace_id": context.workspace_id,
                "undo_operations": undo_operations,
            }
        # Pending already consumed at commit start; clear is a no-op safety net.
        _clear_resource_organization_pending(runtime, context.workspace_id)
        # Completed write wins over a late cancel latch; ack honest failure-to-cancel.
        late_cancel = _take_resource_organization_cancel_requested(
            runtime, context.workspace_id
        )
        _clear_resource_organization_in_flight(runtime, context.workspace_id)
        _stamp_resource_organization_committed(runtime, context.workspace_id)
        ledger = getattr(runtime, "event_ledger", None)
        if ledger is not None and hasattr(ledger, "record_event"):
            ledger.record_event(
                "sandbox_files_reorganized",
                actor="trainer-agent",
                scope="sandbox",
                project_id=context.workspace_id,
                payload_ref={
                    "tool": "organize_resources",
                    "history_id": history_id,
                    "operations": normalized_operations,
                    "batch_checkpoint_id": batch_result.get("checkpoint_id"),
                },
                before_state_ref={"operations": undo_operations},
                after_state_ref={"operations": normalized_operations},
                reversibility="compensatable",
                audit_note="Agent-organized resource sandbox paths after explicit learner confirmation.",
            )

        refresh_sessions = getattr(runtime, "refresh_workspace_sessions", None)
        sessions_refreshed = int(refresh_sessions(context.workspace_id) or 0) if callable(refresh_sessions) else 0
        return {
            "ok": True,
            "committed": True,
            "history_id": history_id,
            "operations": normalized_operations,
            "changes": batch_result.get("changes", []),
            "created_directories": created_directories,
            "deleted_paths": deleted_paths,
            "restored_paths": restored_paths,
            "undo_operations": undo_operations,
            "undo_available": True,
            "sessions_refreshed": sessions_refreshed,
            "audit_recorded": bool(ledger is not None and hasattr(ledger, "record_event")),
            "checkpoint_id": batch_result.get("checkpoint_id"),
            "cancel_failed_already_committed": bool(late_cancel),
            "proposal_restored": False,
        }
    except Exception as exc:
        # The batch rename implementation compensates its own partial moves.
        # Created directories are intentionally left only when cleanup cannot
        # prove they are empty; they remain inside the managed sandbox and are
        # reported for a subsequent explicit cleanup/undo request.
        # Pending was already consumed before FS work — restore so cancel/reconfirm
        # can act on the leftover proposal instead of silently empty-pending.
        # Cancel latch after consume must beat restore: no resurrected pending for a
        # second confirm to silently commit.
        _clear_resource_organization_in_flight(runtime, context.workspace_id)
        cancelled = _take_resource_organization_cancel_requested(
            runtime, context.workspace_id
        )
        proposal_restored = False
        if consumed_pending is not None and not undo_id and not cancelled:
            restore_ops = consumed_pending.get("operations")
            if not isinstance(restore_ops, list) or not restore_ops:
                restore_ops = normalized_operations
            _record_resource_organization_pending(
                runtime, context.workspace_id, list(restore_ops)
            )
            proposal_restored = True
        return {
            "ok": False,
            "error": (
                "resource_organization_cancelled"
                if cancelled
                else "resource_organization_failed"
            ),
            "detail": str(exc),
            "committed": False,
            "requires_confirmation": bool(proposal_restored),
            "proposal_restored": proposal_restored,
            "created_directories": created_directories,
            "operations": normalized_operations,
        }


def _normalize_search_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"broad", "verify"}:
        return normalized
    return "narrow"


def _internal_search_limit(mode: str, limit: int) -> int:
    if mode == "broad":
        return min(24, max(limit * 2, limit + 4))
    if mode == "verify":
        return min(24, max(limit * 3, limit + 4))
    return min(18, max(limit * 2, limit + 2))


def _plain_search_payload(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return value.model_dump()
        except Exception:
            pass
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return asdict(cast(Any, value))
        except Exception:
            pass
    return value


def _normalize_search_response(raw: Any, *, fallback_query: str = "") -> dict[str, Any]:
    payload = _plain_search_payload(raw)
    if isinstance(payload, dict):
        raw_hits = payload.get("hits")
        if not isinstance(raw_hits, list):
            raw_hits = payload.get("results")
        if not isinstance(raw_hits, list):
            raw_hits = payload.get("items")
        hits = _normalize_search_hits(raw_hits if isinstance(raw_hits, list) else [])
        filters_payload = _plain_search_payload(payload.get("filters")) if payload.get("filters") is not None else {}
        filters = filters_payload if isinstance(filters_payload, dict) else {}
        return {
            "query": str(payload.get("query") or fallback_query),
            "total": int(payload.get("total") or len(hits)),
            "ranking_strategy": str(payload.get("ranking_strategy") or payload.get("rankingStrategy") or "lexical_first"),
            "filters": {
                "project_scope": str(filters.get("project_scope") or filters.get("projectScope") or ""),
                "trust_state": str(filters.get("trust_state") or filters.get("trustState") or ""),
                "file_type": str(filters.get("file_type") or filters.get("fileType") or ""),
                "source_type": str(filters.get("source_type") or filters.get("sourceType") or ""),
                "kind": str(filters.get("kind") or ""),
                "index_state": str(filters.get("index_state") or filters.get("indexState") or ""),
            },
            "hits": hits,
        }
    if isinstance(payload, list):
        hits = _normalize_search_hits(payload)
        return {
            "query": fallback_query,
            "total": len(hits),
            "ranking_strategy": "list_only",
            "filters": {},
            "hits": hits,
        }
    return {
        "query": fallback_query,
        "total": 0,
        "ranking_strategy": "unknown",
        "filters": {},
        "hits": [],
    }


def _normalize_search_hits(raw: list[Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in raw:
        entry = _plain_search_payload(item)
        if isinstance(entry, dict):
            updated_at = entry.get("updated_at") or entry.get("updatedAt")
            if isinstance(updated_at, datetime):
                updated_at = updated_at.isoformat()
            hits.append(
                {
                    "id": entry.get("id") or entry.get("resource_id") or entry.get("resourceId"),
                    "resource_id": entry.get("resource_id") or entry.get("resourceId") or entry.get("id"),
                    "title": entry.get("title") or entry.get("name"),
                    "summary": entry.get("summary") or entry.get("excerpt") or entry.get("snippet"),
                    "snippet": entry.get("snippet") or entry.get("excerpt") or entry.get("summary"),
                    "score": entry.get("score") or entry.get("rank_score") or entry.get("rankScore"),
                    "source": entry.get("source") or entry.get("path"),
                    "path": entry.get("path") or entry.get("source"),
                    "source_type": entry.get("source_type") or entry.get("sourceType"),
                    "file_type": entry.get("file_type") or entry.get("fileType"),
                    "project_scope": entry.get("project_scope") or entry.get("projectScope"),
                    "kind": entry.get("kind"),
                    "index_state": entry.get("index_state") or entry.get("indexState"),
                    "citation_id": entry.get("citation_id") or entry.get("citationId"),
                    "trust_score": entry.get("trust_score") or entry.get("trustScore") or 0.0,
                    "trust_state": entry.get("trust_state") or entry.get("trustState") or "",
                    "freshness": entry.get("freshness") or "",
                    "can_inject_training_card": bool(
                        entry.get("can_inject_training_card")
                        if entry.get("can_inject_training_card") is not None
                        else entry.get("canInjectTrainingCard")
                    ),
                    "preview_tier": entry.get("preview_tier") or entry.get("previewTier") or "",
                    "preview_kind": entry.get("preview_kind") or entry.get("previewKind") or "",
                    "rank_score": entry.get("rank_score") or entry.get("rankScore") or entry.get("score") or 0.0,
                    "rank_reasons": entry.get("rank_reasons") or entry.get("rankReasons") or entry.get("reasons") or [],
                    "matched_fields": entry.get("matched_fields") or entry.get("matchedFields") or [],
                    "match_summary": entry.get("match_summary") or entry.get("matchSummary") or "",
                    "updated_at": updated_at,
                    "tags": entry.get("tags") or [],
                }
            )
        else:
            hits.append({"value": str(entry)})
    return hits


def _apply_search_mode(hits: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    if mode != "verify":
        return hits
    verification_ready = [hit for hit in hits if _is_verification_ready_hit(hit)]
    return verification_ready or hits


def _is_verification_ready_hit(hit: dict[str, Any]) -> bool:
    trust_state = str(hit.get("trust_state") or "").strip().lower()
    freshness = str(hit.get("freshness") or "").strip().lower()
    index_state = str(hit.get("index_state") or "").strip().lower()
    try:
        trust_score = float(hit.get("trust_score") or 0.0)
    except Exception:
        trust_score = 0.0
    if trust_state in {"blocked", "rejected", "untrusted"}:
        return False
    if index_state and index_state not in {"indexed", "ready"}:
        return False
    return trust_score >= 0.35 or freshness == "fresh"


def _build_search_summary(
    *,
    query: str,
    mode: str,
    returned_count: int,
    total: int,
    verification_ready_count: int,
    verification_warning: bool,
) -> str:
    if mode == "broad":
        return (
            f"Broad search mapped {returned_count} visible hits out of {total} candidates for '{query}'. "
            "Use a narrower follow-up around the top mechanism, file boundary, API, or example next."
        )
    if mode == "verify":
        suffix = (
            " No hit cleared the trust/freshness gate yet, so the full ranked set is still shown for manual review."
            if verification_warning
            else ""
        )
        return (
            f"Verify search found {verification_ready_count} citation-ready hits and returned {returned_count} visible results for '{query}'."
            f"{suffix}"
        )
    return (
        f"Narrow search kept {returned_count} visible hits out of {total} candidates for '{query}'. "
        "Use these to answer the current question before widening scope again."
    )


# --- read_workspace_file ------------------------------------------------


def _sandbox_service(context: ToolContext) -> Any | None:
    return getattr(context.runtime, "sandbox_service", None) if context.runtime is not None else None


def _sandbox_resource_kind(path: str) -> Literal["pdf", "image", "text", "markdown", "code", "url"]:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".go", ".rs", ".toml", ".yaml", ".yml"}:
        return "code"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def _flatten_sandbox_nodes(nodes: Any, *, limit: int, items: list[dict[str, Any]]) -> None:
    for node in nodes or []:
        if len(items) >= limit:
            return
        relative = str(getattr(node, "relative_path", "") or getattr(node, "path", "") or "")
        items.append(
            {
                "path": relative.replace("\\", "/"),
                "name": str(getattr(node, "name", "") or Path(relative).name),
                "kind": str(getattr(node, "node_kind", "") or ""),
                "resource_id": getattr(node, "resource_id", None),
                "size_bytes": int(getattr(node, "size_bytes", 0) or 0),
                "is_editable": bool(getattr(node, "is_editable", False)),
            }
        )
        children = getattr(node, "children", None) or []
        if children:
            _flatten_sandbox_nodes(children, limit=limit, items=items)


def _sandbox_preview_payload(preview: Any, *, max_chars: int) -> dict[str, Any]:
    if hasattr(preview, "model_dump") and callable(preview.model_dump):
        try:
            payload = preview.model_dump(mode="json")
        except TypeError:
            payload = preview.model_dump()
    elif isinstance(preview, dict):
        payload = dict(preview)
    else:
        payload = {"path": str(preview)}
    payload.pop("html", None)
    content = str(payload.get("content") or "")
    if len(content) > max_chars:
        payload["content"] = content[:max_chars]
        payload["truncated"] = True
    excerpt = str(payload.get("excerpt") or "")
    if len(excerpt) > min(400, max_chars):
        payload["excerpt"] = excerpt[: min(400, max_chars)]
    return payload if isinstance(payload, dict) else {}


def _reindex_matching_sandbox_resource(context: ToolContext, relative_path: str) -> dict[str, Any] | None:
    runtime = context.runtime
    resource_service = getattr(runtime, "resource_service", None) if runtime is not None else None
    if resource_service is None or not hasattr(resource_service, "index"):
        return None
    resource = _match_resource_by_sandbox_path(runtime, context.workspace_id, relative_path)
    if resource is None:
        return None
    resource_id = str(getattr(resource, "id", "") or "").strip()
    if not resource_id:
        return None
    try:
        indexed = resource_service.index(
            context.workspace_id,
            ResourceIndexRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                resource_id=resource_id,
                enable_network=False,
            ),
        )
    except Exception:
        return {"resource_id": resource_id, "reindexed": False}
    postprocess = getattr(runtime, "postprocess_indexed_resource", None)
    if callable(postprocess):
        try:
            postprocessed = postprocess(context.workspace_id, indexed, refresh_sessions=True)
            if isinstance(postprocessed, tuple) and postprocessed:
                indexed = postprocessed[0]
            elif postprocessed is not None:
                indexed = postprocessed
        except Exception:
            pass
    return {
        "resource_id": resource_id,
        "reindexed": True,
        "index_status": getattr(indexed, "index_status", None),
        "sandbox_path": getattr(indexed, "sandbox_path", None),
    }


async def _handle_list_sandbox(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    sandbox_service = _sandbox_service(context)
    if sandbox_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "The managed sandbox is not configured."}
    try:
        limit = max(1, min(int(args.get("limit", 80)), 200))
    except Exception:
        limit = 80
    runtime = context.runtime
    repository = getattr(runtime, "repository", None)
    resources = []
    if repository is not None and hasattr(repository, "list_resources"):
        try:
            resources = list(repository.list_resources(context.workspace_id) or [])
        except Exception:
            resources = []
    try:
        state = sandbox_service.list_state(
            context.workspace_id,
            resources,
            workspace_root_path=getattr(runtime, "resolve_workspace_path", lambda _workspace_id: None)(
                context.workspace_id
            ),
        )
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    items: list[dict[str, Any]] = []
    _flatten_sandbox_nodes(getattr(state, "nodes", None) or [], limit=limit, items=items)
    return {
        "ok": True,
        "root": str(getattr(state, "sandbox_root_path", "") or getattr(state, "root_path", "") or ""),
        "total_files": int(getattr(state, "total_files", 0) or 0),
        "total_directories": int(getattr(state, "total_directories", 0) or 0),
        "linked_resource_count": int(getattr(state, "linked_resource_count", 0) or 0),
        "items": items,
    }


async def _handle_read_sandbox_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    sandbox_service = _sandbox_service(context)
    if sandbox_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "The managed sandbox is not configured."}
    try:
        relative = _safe_sandbox_relative_path(args.get("path"), field_name="path")
    except ValueError as exc:
        return {"ok": False, "error": "invalid_path", "detail": str(exc)}
    try:
        max_chars = max(64, min(int(args.get("max_chars", 8000)), 32000))
    except Exception:
        max_chars = 8000
    try:
        preview = sandbox_service.preview(
            context.workspace_id,
            SandboxPreviewRequest(workspace_id=context.workspace_id, path=relative),
        )
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    payload = _sandbox_preview_payload(preview, max_chars=max_chars)
    payload["ok"] = True
    payload["path"] = relative
    return payload


async def _handle_write_sandbox_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    sandbox_service = _sandbox_service(context)
    if sandbox_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "The managed sandbox is not configured."}
    try:
        relative = _safe_sandbox_relative_path(args.get("path"), field_name="path")
    except ValueError as exc:
        return {"ok": False, "error": "invalid_path", "detail": str(exc)}
    content = args.get("content")
    if content is None:
        return {"ok": False, "error": "missing_content", "detail": "write_sandbox_file requires content."}
    text = content if isinstance(content, str) else str(content)
    create = args.get("create") is not False
    try:
        preview = sandbox_service.write(
            context.workspace_id,
            SandboxWriteRequest(
                workspace_id=context.workspace_id,
                path=relative,
                content=text,
                create=create,
                explicit_destructive_policy=True,
            ),
        )
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    reindexed = _reindex_matching_sandbox_resource(context, relative)
    payload = _sandbox_preview_payload(preview, max_chars=4000)
    payload["ok"] = True
    payload["path"] = relative
    payload["written"] = True
    payload["bytes"] = len(text.encode("utf-8", errors="replace"))
    if reindexed is not None:
        payload["library"] = reindexed
    return payload


async def _handle_index_sandbox_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    sandbox_service = _sandbox_service(context)
    resource_service = getattr(context.runtime, "resource_service", None) if context.runtime is not None else None
    if sandbox_service is None or resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The managed sandbox or resource library is not configured.",
        }
    try:
        relative = _safe_sandbox_relative_path(args.get("path"), field_name="path")
    except ValueError as exc:
        return {"ok": False, "error": "invalid_path", "detail": str(exc)}
    root = sandbox_service.ensure_operation_root(context.workspace_id)
    absolute = str((Path(root) / relative).resolve())
    existing = _match_resource_by_sandbox_path(context.runtime, context.workspace_id, relative)
    if existing is not None:
        reindexed = _reindex_matching_sandbox_resource(context, relative)
        return {
            "ok": True,
            "committed": True,
            "path": relative,
            "resource_id": getattr(existing, "id", None),
            "library": reindexed,
        }
    name = str(args.get("name") or Path(relative).name or "sandbox-note").strip()[:200]
    kind = _sandbox_resource_kind(relative)
    raw_tags = args.get("tags")
    tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()][:20] if isinstance(raw_tags, list) else []
    try:
        uploaded = resource_service.upload(
            context.workspace_id,
            ResourceUploadRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                kind=kind,
                name=name,
                source=absolute,
                source_type="file",
                tags=tags,
            ),
            workspace_path=str(root),
        )
        if inspect.isawaitable(uploaded):
            uploaded = await uploaded
        updated = uploaded.model_copy(
            update={"sandbox_path": absolute, "sandbox_dirty": False}
        )
        repository = getattr(context.runtime, "repository", None)
        if repository is not None and hasattr(repository, "save_resource"):
            repository.save_resource(context.workspace_id, updated)
        indexed = resource_service.index(
            context.workspace_id,
            ResourceIndexRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                resource_id=str(getattr(updated, "id", "") or ""),
                enable_network=False,
            ),
        )
        if inspect.isawaitable(indexed):
            indexed = await indexed
        indexed = indexed.model_copy(update={"sandbox_path": absolute, "sandbox_dirty": False})
        if repository is not None and hasattr(repository, "save_resource"):
            repository.save_resource(context.workspace_id, indexed)
        postprocess = getattr(context.runtime, "postprocess_indexed_resource", None)
        if callable(postprocess):
            postprocessed = postprocess(context.workspace_id, indexed, refresh_sessions=True)
            if inspect.isawaitable(postprocessed):
                postprocessed = await postprocessed
            if isinstance(postprocessed, tuple) and postprocessed:
                indexed = postprocessed[0]
            elif postprocessed is not None:
                indexed = postprocessed
            indexed = indexed.model_copy(update={"sandbox_path": absolute, "sandbox_dirty": False})
            if repository is not None and hasattr(repository, "save_resource"):
                repository.save_resource(context.workspace_id, indexed)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc), "path": relative}
    payload = _resource_model_payload(indexed)
    return {
        "ok": True,
        "committed": True,
        "path": relative,
        "resource_id": payload.get("id"),
        "index_status": payload.get("index_status"),
        "sandbox_path": payload.get("sandbox_path") or absolute,
        "resource": payload,
    }


async def _handle_inspect_current_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    current_file = context.extra.get("current_file") if isinstance(context.extra, dict) else None
    if not isinstance(current_file, dict):
        return {
            "ok": False,
            "error": "no_current_file",
            "detail": "No active IDE file snapshot was provided for this turn.",
        }
    try:
        max_chars = max(64, min(int(args.get("max_chars", 8000)), 32000))
    except Exception:
        max_chars = 8000

    content = current_file.get("content_excerpt") or current_file.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    diagnostics = current_file.get("diagnostics")
    selection_text = current_file.get("selection_text")
    result: dict[str, Any] = {
        "ok": True,
        "path": str(current_file.get("path") or "unknown"),
        "language_id": str(current_file.get("language_id") or "unknown"),
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
        "diagnostics": diagnostics[:20] if isinstance(diagnostics, list) else [],
    }
    for key in ("content_line_span", "content_strategy", "selection_range"):
        value = current_file.get(key)
        if value:
            result[key] = value
    if isinstance(selection_text, str) and selection_text:
        result["selection_text"] = selection_text[:max_chars]
        result["selection_truncated"] = len(selection_text) > max_chars
    return result


_PRACTICE_SIGNAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "when",
    "then",
    "should",
    "must",
    "have",
    "has",
    "use",
    "uses",
    "using",
    "add",
    "make",
    "create",
    "return",
    "returns",
    "value",
    "values",
    "file",
    "code",
    "current",
    "实现",
    "使用",
    "需要",
    "应该",
    "当前",
    "文件",
    "代码",
}


def _diagnostic_severity(diagnostic: Any) -> str:
    text = str(diagnostic or "").strip().lower()
    match = re.match(r"^\[(error|warning|info|hint|unknown)\]", text)
    if match:
        return match.group(1)
    if "error" in text or "错误" in text:
        return "error"
    if "warning" in text or "警告" in text:
        return "warning"
    if "hint" in text:
        return "hint"
    return "info" if text else "unknown"


def _practice_signals(text: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.$-]*|[\u4e00-\u9fff]{2,}", text)
    signals: list[str] = []
    for token in raw_tokens:
        normalized = token.strip("._-$").lower()
        if len(normalized) < 3 or normalized in _PRACTICE_SIGNAL_STOPWORDS:
            continue
        if normalized not in signals:
            signals.append(normalized)
    return signals[:8]


def _criterion_result(criterion: str, content_lower: str) -> dict[str, Any]:
    signals = _practice_signals(criterion)
    if not signals:
        criterion_lower = criterion.strip().lower()
        matched = bool(criterion_lower and criterion_lower in content_lower)
        return {
            "text": criterion,
            "status": "matched" if matched else "not_verifiable",
            "matched_signals": [criterion.strip()] if matched else [],
            "missing_signals": [] if matched else [criterion.strip()],
        }
    matched_signals = [signal for signal in signals if signal in content_lower]
    required_matches = 1 if len(signals) <= 2 else 2
    matched = len(matched_signals) >= required_matches
    return {
        "text": criterion,
        "status": "matched" if matched else "missing",
        "matched_signals": matched_signals,
        "missing_signals": [signal for signal in signals if signal not in matched_signals],
    }


async def _handle_verify_practice_current_file(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    current_file = context.extra.get("current_file") if isinstance(context.extra, dict) else None
    if not isinstance(current_file, dict):
        return {
            "ok": False,
            "error": "no_current_file",
            "status": "blocked",
            "passed": False,
            "detail": "Practice verification requires the active IDE file snapshot.",
            "next_step": "Open the learner's implementation file and run Verify current file again.",
        }

    content = current_file.get("content") or current_file.get("content_excerpt") or ""
    if not isinstance(content, str):
        content = str(content)
    if not content.strip():
        return {
            "ok": False,
            "error": "empty_current_file",
            "status": "blocked",
            "passed": False,
            "path": str(current_file.get("path") or "unknown"),
            "detail": "The active IDE file has no readable content.",
            "next_step": "Save or focus the implementation file, then verify the current file again.",
        }

    raw_diagnostics = current_file.get("diagnostics")
    diagnostics = [str(item) for item in raw_diagnostics if str(item).strip()] if isinstance(raw_diagnostics, list) else []
    error_diagnostics = [item for item in diagnostics if _diagnostic_severity(item) == "error"]
    warning_diagnostics = [item for item in diagnostics if _diagnostic_severity(item) == "warning"]
    allow_warnings = bool(args.get("allow_warnings") is True)

    criteria = [
        str(item).strip()
        for item in args.get("acceptance_criteria", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("acceptance_criteria"), list) else []
    expected_symbols = [
        str(item).strip()
        for item in args.get("expected_symbols", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("expected_symbols"), list) else []
    check_items = [*criteria, *expected_symbols]
    content_lower = content.lower()
    criterion_results = [_criterion_result(item, content_lower) for item in check_items]
    missing_results = [item for item in criterion_results if item.get("status") != "matched"]

    path = str(current_file.get("path") or "unknown")
    language_id = str(current_file.get("language_id") or "unknown")
    evidence = [
        f"Read active IDE file {path} ({language_id}).",
        f"Current file content length: {len(content)} characters.",
    ]
    if current_file.get("selection_range"):
        evidence.append(f"Selection attached: {current_file.get('selection_range')}.")
    if diagnostics:
        evidence.append(f"VS Code diagnostics attached: {len(diagnostics)}.")
    for item in criterion_results:
        if item.get("status") == "matched":
            evidence.append(f"Matched: {item.get('text')}")

    if error_diagnostics:
        status = "blocked"
        passed = False
        reason = "error_diagnostics"
        summary = "Current-file practice verification is blocked by VS Code error diagnostics."
        next_step = "Fix the error diagnostics in the active file, then run Verify current file again."
    elif warning_diagnostics and not allow_warnings:
        status = "needs_review"
        passed = False
        reason = "warning_diagnostics"
        summary = "The active file was read, but warning diagnostics need review before marking the practice passed."
        next_step = "Review the warning diagnostics or rerun verification with warnings explicitly allowed."
    elif not check_items:
        status = "needs_review"
        passed = False
        reason = "missing_acceptance_criteria"
        summary = "The active file was read, but no acceptance criteria were supplied."
        next_step = "Provide concrete acceptance criteria or expected symbols for this practice card."
    elif missing_results:
        status = "needs_review"
        passed = False
        reason = "missing_acceptance_signals"
        summary = "The active file was read, but not all practice acceptance signals were found."
        next_step = "Implement the missing acceptance signals, then run Verify current file again."
    else:
        status = "passed"
        passed = True
        reason = "all_signals_matched"
        summary = "The active IDE file matches the supplied practice acceptance signals with no blocking diagnostics."
        next_step = "Return to Training and mark the practice result as verified evidence."

    try:
        max_evidence = max(1, min(int(args.get("max_evidence", 8) or 8), 20))
    except Exception:
        max_evidence = 8

    payload = {
        "ok": True,
        "tool": "verify_practice_current_file",
        "status": status,
        "passed": passed,
        "reason": reason,
        "evidence_source": "ide_current_file",
        "path": path,
        "language_id": language_id,
        "diagnostics_count": len(diagnostics),
        "blocking_diagnostics": error_diagnostics[:8],
        "warning_diagnostics": warning_diagnostics[:8],
        "criteria": criterion_results,
        "evidence": evidence[:max_evidence],
        "summary": summary,
        "next_step": next_step,
    }
    persistence = _persist_practice_verification_result(
        context,
        payload=payload,
        args=args,
        current_file=current_file,
        missing_results=missing_results,
    )
    if persistence:
        payload.update(persistence)
    return payload


def _persist_practice_verification_result(
    context: ToolContext,
    *,
    payload: dict[str, Any],
    args: dict[str, Any],
    current_file: dict[str, Any],
    missing_results: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None) if runtime is not None else None
    if memory_service is None or not hasattr(memory_service, "record_training_practice_evaluation_result"):
        return {}

    workspace_id = context.workspace_id
    card_id, card_title, focus_area = _training_card_context_for_persistence(
        context,
        args=args,
        current_file=current_file,
    )
    if not card_id and not card_title:
        return {}

    failed_checks = _practice_failed_checks(payload)
    missing_requirements = [
        str(item.get("text") or "").strip()
        for item in missing_results
        if str(item.get("text") or "").strip()
    ]
    if not missing_requirements and payload.get("passed") is False:
        missing_requirements = [
            str(item).strip()
            for item in [
                *(payload.get("blocking_diagnostics") or []),
                *(payload.get("warning_diagnostics") or []),
            ]
            if str(item).strip()
        ]
    try:
        workspace_update = memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=card_id,
            card_title=card_title,
            passed=bool(payload.get("passed")),
            summary=str(payload.get("summary") or ""),
            next_step=str(payload.get("next_step") or ""),
            focus_area=focus_area or str(current_file.get("path") or "practice verification"),
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=str(payload.get("evidence_source") or "ide_current_file"),
            verified_by_evaluator=True,
        )
    except Exception as exc:
        return {
            "persisted_training_evidence": False,
            "training_evidence_error": exc.__class__.__name__,
            "training_evidence_detail": str(exc),
        }
    return {
        "persisted_training_evidence": True,
        "training_card_id": card_id,
        "training_card_title": card_title,
        "training_workspace_update": workspace_update,
    }


def _leftover_training_persist_identity(
    context: ToolContext,
) -> tuple[Any, dict[str, Any], str]:
    runtime = context.runtime
    if runtime is None:
        return None, {}, ""
    memory_service = getattr(runtime, "memory_service", None)
    leftover_ctx = getattr(memory_service, "_leftover_persist_context", None) if memory_service is not None else None
    if callable(leftover_ctx):
        try:
            leftover_plan, leftover_runtime, leftover_task_title = leftover_ctx(context.workspace_id)
        except Exception:
            leftover_plan, leftover_runtime, leftover_task_title = None, {}, ""
        else:
            return (
                leftover_plan,
                leftover_runtime if isinstance(leftover_runtime, dict) else {},
                str(leftover_task_title or "").strip(),
            )
    from ..memory.workspace_recovery import (
        CURRENT_TASK_KEY,
        PLAN_RUNTIME_KEY,
        normalize_latest_current_task,
        select_plan_runtime_for_scope,
    )

    leftover_plan = None
    leftover_runtime: dict[str, Any] = {}
    leftover_task_title = ""
    try:
        repository = getattr(runtime, "repository", None)
        leftover_plan = repository.get_latest_plan(context.workspace_id) if repository is not None else None
        if memory_service is None:
            return leftover_plan, leftover_runtime, leftover_task_title
        snapshot = memory_service.snapshot(context.workspace_id)
        workspace = snapshot.workspace if isinstance(getattr(snapshot, "workspace", None), dict) else {}
        recovered = select_plan_runtime_for_scope(
            workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
            context.workspace_id,
        )
        leftover_runtime = recovered if isinstance(recovered, dict) else {}
        task = normalize_latest_current_task(
            workspace.get(CURRENT_TASK_KEY)
            or workspace.get("current_task")
            or workspace.get("currentTask"),
            context.workspace_id,
        ) or {}
        leftover_task_title = str(task.get("title") or "").strip()
    except Exception:
        return leftover_plan, leftover_runtime, leftover_task_title
    return leftover_plan, leftover_runtime, leftover_task_title


def _training_card_context_for_persistence(
    context: ToolContext,
    *,
    args: dict[str, Any],
    current_file: dict[str, Any],
) -> tuple[str, str, str]:
    from ..memory.workspace_recovery import live_training_card_title

    card_id = str(
        args.get("training_card_id")
        or args.get("card_id")
        or current_file.get("training_card_id")
        or ""
    ).strip()
    card_title = str(
        args.get("training_card_title")
        or args.get("card_title")
        or current_file.get("training_card_title")
        or ""
    ).strip()
    focus_area = str(args.get("focus_area") or current_file.get("focus_area") or "").strip()

    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None) if runtime is not None else None
    if memory_service is not None and not (card_id and card_title and focus_area):
        try:
            snapshot = memory_service.snapshot(context.workspace_id)
        except Exception:
            snapshot = None
        routing = getattr(snapshot, "active_training_card_routing", None) if snapshot is not None else None
        selected = getattr(routing, "selected_card", None) if routing is not None else None
        if not card_id:
            card_id = str(
                getattr(routing, "selected_card_id", "") or getattr(selected, "card_id", "") or ""
            ).strip()
        if selected is not None:
            if not card_title:
                card_title = str(getattr(selected, "title", "") or "").strip()
            if not focus_area:
                focus_area = str(
                    getattr(selected, "focus_area", "") or getattr(selected, "target_skill", "") or ""
                ).strip()
    leftover_plan, leftover_runtime, leftover_task_title = _leftover_training_persist_identity(context)
    card_title = live_training_card_title(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=leftover_task_title,
        card_title=card_title,
    )
    if focus_area:
        focus_area = live_training_card_title(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=focus_area,
        )
    return card_id, card_title, focus_area


def _practice_failed_checks(payload: dict[str, Any]) -> list[str]:
    if payload.get("passed") is True:
        return []
    reason = str(payload.get("reason") or "").strip()
    checks: list[str] = []
    if reason:
        checks.append(reason)
    if payload.get("blocking_diagnostics"):
        checks.append("vscode-diagnostics")
    if payload.get("warning_diagnostics"):
        checks.append("vscode-warnings")
    return list(dict.fromkeys(checks))


async def _handle_read_workspace_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path_raw = str(args.get("path") or "").strip()
    if not path_raw:
        return {"ok": False, "error": "missing_path", "detail": "read_workspace_file requires a path."}
    try:
        max_chars = max(64, min(int(args.get("max_chars", 4000)), 16000))
    except Exception:
        max_chars = 4000

    root = _resolve_workspace_root(context)
    target = _safe_path_under(root, path_raw) if root is not None else None
    if target is not None and target.is_file():
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        truncated = len(text) > max_chars
        return {
            "ok": True,
            "path": str(target.relative_to(root)) if root is not None else str(target),
            "absolute_path": str(target),
            "source": "workspace_disk",
            "truncated": truncated,
            "content": text[:max_chars],
            "byte_size": len(text.encode("utf-8", errors="replace")),
        }
    record = _snapshot_file_record(context, path_raw)
    if record is not None:
        text = str(record.get("content") or "")
        truncated = len(text) > max_chars
        return {
            "ok": True,
            "path": str(record.get("path") or path_raw),
            "source": "workspace_snapshot",
            "truncated": truncated,
            "content": text[:max_chars],
            "byte_size": len(text.encode("utf-8", errors="replace")),
            "language_id": record.get("language_id"),
        }
    if _snapshot_file_listed(context, path_raw):
        relative = _normalize_workspace_relpath(path_raw)
        remember = getattr(context.runtime, "remember_requested_workspace_file", None) if context.runtime is not None else None
        if callable(remember):
            remember(context.workspace_id, relative)
        return {
            "ok": False,
            "error": "snapshot_content_unavailable",
            "listed": True,
            "path": relative,
            "detail": (
                f"Path {path_raw!r} is listed in the host workspace snapshot, "
                "but this turn did not include its file body. Open the file in the editor "
                "or import it on a later turn after the host refreshes the snapshot."
            ),
        }
    return {
        "ok": False,
        "error": "not_found",
        "detail": f"Path {path_raw!r} is not a readable file inside the active workspace.",
    }


# --- list_workspace_files -----------------------------------------------


async def _handle_list_workspace_files(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    pattern_raw = str(args.get("pattern") or "**/*").strip() or "**/*"
    try:
        limit = max(1, min(int(args.get("limit", 30)), 200))
    except Exception:
        limit = 30
    root = _resolve_workspace_root(context)
    if pattern_raw.startswith("/"):
        return {
            "ok": False,
            "error": "absolute_pattern_rejected",
            "detail": "Pattern must be relative to the workspace root.",
        }
    if root is not None:
        try:
            matches = list(root.glob(pattern_raw))
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        items: list[dict[str, Any]] = []
        for path in matches[:limit]:
            try:
                stat = path.stat()
            except Exception:
                continue
            items.append(
                {
                    "path": str(path.relative_to(root)),
                    "is_dir": path.is_dir(),
                    "size": stat.st_size,
                }
            )
        return {"ok": True, "pattern": pattern_raw, "items": items, "total_seen": len(matches), "source": "workspace_disk"}
    snapshot_items = _snapshot_file_list(context)
    if not snapshot_items:
        return {
            "ok": False,
            "error": "no_workspace",
            "detail": "No workspace path is currently available; the learner has not opened a folder.",
        }
    filtered = [
        item
        for item in snapshot_items
        if _snapshot_path_matches(str(item.get("path") or ""), pattern_raw)
    ]
    return {
        "ok": True,
        "pattern": pattern_raw,
        "items": filtered[:limit],
        "total_seen": len(filtered),
        "source": "workspace_snapshot",
    }


async def _handle_import_workspace_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Copy a learner-project file into the local Trainer library/sandbox."""

    path_raw = str(args.get("path") or "").strip()
    if not path_raw:
        return {"ok": False, "error": "missing_path", "detail": "import_workspace_file requires a path."}
    relative = _normalize_workspace_relpath(path_raw)
    text: str | None = None
    source = "workspace_snapshot"
    root = _resolve_workspace_root(context)
    target = _safe_path_under(root, path_raw) if root is not None else None
    if target is not None and target.is_file():
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            source = "workspace_disk"
            relative = str(target.relative_to(root)).replace("\\", "/") if root is not None else relative
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    if text is None:
        record = _snapshot_file_record(context, path_raw)
        if record is None:
            if _snapshot_file_listed(context, path_raw):
                remember = getattr(context.runtime, "remember_requested_workspace_file", None) if context.runtime is not None else None
                if callable(remember):
                    remember(context.workspace_id, relative)
                return {
                    "ok": False,
                    "error": "snapshot_content_unavailable",
                    "listed": True,
                    "path": relative,
                    "detail": (
                        f"Path {path_raw!r} is listed in the host workspace snapshot, "
                        "but this turn did not include its file body so it cannot be imported yet."
                    ),
                }
            return {
                "ok": False,
                "error": "not_found",
                "detail": f"Path {path_raw!r} is not available in the host workspace snapshot.",
            }
        text = str(record.get("content") or "")
        relative = str(record.get("path") or relative)
    if not text.strip():
        return {"ok": False, "error": "empty_file", "detail": f"Path {relative!r} has no importable text."}
    dest = f"sources/workspace/{relative.lstrip('/')}"
    written = await _handle_write_sandbox_file(context, {"path": dest, "content": text, "create": True})
    if written.get("ok") is not True:
        return written
    indexed = await _handle_index_sandbox_file(
        context,
        {
            "path": dest,
            "name": Path(relative).name,
            "tags": ["workspace", "remote"] if _workspace_file_snapshot(context).get("is_remote") else ["workspace"],
        },
    )
    return {
        "ok": True,
        "imported": True,
        "source": source,
        "workspace_path": relative,
        "sandbox_path": dest,
        "bytes": len(text.encode("utf-8", errors="replace")),
        "library": indexed if indexed.get("ok") is True else None,
    }


# --- recall_memory -------------------------------------------------------


async def _handle_recall_memory(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": (
                "No saved learner memory is attached to this run, so continue "
                "from the current message and visible workspace context."
            ),
        }
    snapshot_callable = getattr(memory_service, "snapshot", None)
    if snapshot_callable is None:
        return {"ok": False, "error": "unsupported", "detail": "memory_service.snapshot is missing."}
    try:
        snapshot = snapshot_callable(context.workspace_id)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    payload = _summarize_memory_snapshot(snapshot)
    focus = str(args.get("focus") or "").strip()
    if focus:
        payload["focus"] = focus
    return {"ok": True, **payload}


def _summarize_memory_snapshot(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {"summary": "memory snapshot empty"}
    data: dict[str, Any]
    if hasattr(snapshot, "model_dump"):
        try:
            data = snapshot.model_dump(mode="json")
        except Exception:
            data = {}
    elif isinstance(snapshot, dict):
        data = dict(snapshot)
    else:
        data = {}
    summary: dict[str, Any] = {}
    for key in (
        "current_focus",
        "active_thread",
        "review_rhythm",
        "due_reviews",
        "learning_outcomes",
        "teaching_observations",
        "remembered_preferences",
    ):
        value = data.get(key)
        if value:
            summary[key] = value
    if not summary:
        summary["summary"] = "memory snapshot present but has no actionable signals yet"
    return summary


# --- record_learning_note -----------------------------------------------


async def _handle_record_learning_note(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not _explicit_learning_note_request_allowed(context):
        return {
            "ok": False,
            "error": "explicit_learning_note_request_required",
            "detail": "This write is only available when the learner explicitly asked to record a learning note.",
        }
    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is None:
        return {"ok": False, "error": "service_unavailable"}
    note = str(args.get("note") or "").strip()
    if not note:
        return {"ok": False, "error": "missing_note", "detail": "note must be non-empty."}
    kind = str(args.get("kind") or "observation").strip() or "observation"
    record_fn = (
        getattr(memory_service, "record_teaching_observation", None)
        or getattr(memory_service, "record_observation", None)
        or getattr(memory_service, "record_session_note", None)
    )
    if record_fn is None:
        return {
            "ok": False,
            "error": "unsupported",
            "detail": "memory_service has no observation-recording API.",
        }
    try:
        record_result = record_fn(
            workspace_id=context.workspace_id,
            note=note,
            kind=kind,
        )
        if inspect.isawaitable(record_result):
            await record_result
    except TypeError:
        try:
            record_result = record_fn(context.workspace_id, note)
            if inspect.isawaitable(record_result):
                await record_result
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {"ok": True, "kind": kind, "note": note}


# --- inspect_plan / advance_plan_stage ---------------------------------


async def _handle_inspect_plan(context: ToolContext, _: dict[str, Any]) -> dict[str, Any]:
    runtime = context.runtime
    repository = getattr(runtime, "repository", None)
    if repository is None:
        return {"ok": False, "error": "service_unavailable"}
    plan = None
    if hasattr(repository, "get_latest_plan"):
        try:
            plan = repository.get_latest_plan(context.workspace_id)
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    if plan is None:
        return {"ok": True, "plan": None, "summary": "no plan exists for this workspace yet"}
    payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    summary = _summarize_plan(payload)
    return {"ok": True, "plan": payload, "summary": summary}


def _summarize_plan(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    stages = payload.get("stages") or []
    active = next(
        (stage for stage in stages if isinstance(stage, dict) and stage.get("status") == "active"),
        None,
    )
    return {
        "title": payload.get("title"),
        "stage_count": len(stages),
        "active_stage": active,
        "next_step": payload.get("next_step"),
    }


# --- save_formal_plan --------------------------------------------------


def _tool_text_list(value: object, *, limit: int = 12, item_limit: int = 320) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split()).strip()
        if text and text not in result:
            result.append(text[:item_limit])
        if len(result) >= limit:
            break
    return result


async def _handle_save_formal_plan(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Persist a plan that the model has shaped from the live conversation.

    This is intentionally a separate, explicitly-authorized write. The
    planner service remains responsible for deterministic lifecycle updates;
    this tool is the boundary where an agent may commit a user-visible plan.
    """
    if context.extra.get("formal_plan_mutation") is not True:
        return {
            "ok": False,
            "error": "formal_plan_mutation_required",
            "detail": "This write is only available during an explicit formal plan turn.",
        }
    runtime = context.runtime
    repository = getattr(runtime, "repository", None)
    if repository is None:
        return {"ok": False, "error": "service_unavailable"}

    existing = None
    try:
        existing = repository.get_latest_plan(context.workspace_id)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    leftover_plan, leftover_runtime, _leftover_task = _leftover_training_persist_identity(context)
    from ..memory.workspace_recovery import (
        leftover_formal_plan_identity_labels,
        leftover_formal_plan_is_live_for_fill,
    )

    live_existing = bool(
        existing is not None
        and leftover_formal_plan_is_live_for_fill(
            plan=leftover_plan or existing,
            runtime=leftover_runtime,
            existing=leftover_runtime,
        )
    )
    if existing is not None and bool(getattr(existing, "frozen", False)) and live_existing:
        return {
            "ok": False,
            "error": "plan_frozen",
            "detail": "The current formal plan is frozen and cannot be changed in this turn.",
        }

    raw_stages = args.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        return {"ok": False, "error": "stages_required", "detail": "At least one plan stage is required."}

    stages: list[PlanStage] = []
    for index, raw_stage in enumerate(raw_stages[:12]):
        if not isinstance(raw_stage, dict):
            continue
        title = " ".join(str(raw_stage.get("title") or "").split()).strip()
        goal = " ".join(str(raw_stage.get("goal") or raw_stage.get("objective") or "").split()).strip()
        if not title or not goal:
            continue
        stage_id = " ".join(str(raw_stage.get("id") or f"stage-{index + 1}").split()).strip()
        status = str(raw_stage.get("status") or ("active" if index == 0 else "pending")).strip().lower()
        if status not in {"pending", "active", "completed"}:
            status = "pending"
        stages.append(
            PlanStage(
                id=stage_id[:120],
                title=title[:240],
                goal=goal[:600],
                outcomes=_tool_text_list(raw_stage.get("outcomes"), limit=8),
                resources=_tool_text_list(raw_stage.get("resources"), limit=12, item_limit=160),
                status=cast(Literal["pending", "active", "completed"], status),
            )
        )
    if not stages:
        return {
            "ok": False,
            "error": "invalid_stages",
            "detail": "Every plan stage needs a title and a concrete goal.",
        }
    if not any(stage.status == "active" for stage in stages):
        stages[0].status = "active"

    title = " ".join(str(args.get("title") or "").split()).strip()
    summary = " ".join(str(args.get("summary") or args.get("objective") or "").split()).strip()
    if not title or not summary:
        return {
            "ok": False,
            "error": "plan_identity_required",
            "detail": "A plan title and summary are required.",
        }
    active_stage = next((stage for stage in stages if stage.status == "active"), stages[0])
    next_stage = next((stage for stage in stages if stage.id != active_stage.id and stage.status == "pending"), None)
    leftover_identity = leftover_formal_plan_identity_labels(
        plan=leftover_plan if not live_existing else None
    )
    recovered_step = ""
    if isinstance(leftover_runtime, dict):
        recovered_step = str(
            leftover_runtime.get("current_step") or leftover_runtime.get("currentStep") or ""
        ).strip()
    if recovered_step in leftover_identity:
        recovered_step = ""
    current_step = " ".join(str(args.get("current_step") or active_stage.goal).split()).strip()[:600]
    if not live_existing and current_step in leftover_identity:
        current_step = recovered_step
    plan = LearningPlan(
        id=(existing.id if live_existing and existing is not None else f"plan-{uuid4().hex}"),
        title=title[:240],
        summary=summary[:1200],
        stages=stages,
        cadence=" ".join(str(args.get("cadence") or args.get("weekly_cadence") or "").split())[:240],
        current_stage_id=active_stage.id,
        current_step=current_step,
        why_now=" ".join(str(args.get("why_now") or "").split()).strip()[:600],
        verify_method=_tool_text_list(args.get("verify_method"), limit=8),
        blocked_reason=" ".join(str(args.get("blocked_reason") or "").split()).strip()[:600],
        next_after_current=(
            " ".join(str(args.get("next_after_current") or (next_stage.goal if next_stage else "Review the result and decide whether to widen scope.")).split()).strip()[:600]
        ),
    )
    try:
        repository.save_plan(context.workspace_id, plan)
        bind_generated = getattr(getattr(runtime, "memory_service", None), "bind_explicit_generated_plan", None)
        if callable(bind_generated):
            bind_generated(context.workspace_id, plan)
        sandbox_service = getattr(runtime, "sandbox_service", None)
        if sandbox_service is not None:
            sandbox_service.persist_plan_snapshot(context.workspace_id, plan, reason="model-formal-plan")
        for session_state in getattr(runtime, "sessions", {}).values():
            if session_state.workspace_id != context.workspace_id:
                continue
            session_state.snapshot.plan = plan.model_copy(deep=True)
            runtime.save_session_state(session_state.session_id)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {
        "ok": True,
        "committed": True,
        "plan": plan.model_dump(mode="json"),
        "summary": _summarize_plan(plan.model_dump(mode="json")),
    }


# --- specify_task / next_task ------------------------------------------


async def _handle_specify_task(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Mint TaskSpec for a live-bound formal plan only (HTTP /task/specify parity)."""
    if not _task_mint_tool_allowed(context):
        return {
            "ok": False,
            "error": "live_formal_plan_required",
            "detail": (
                "specify_task requires a live-bound formal plan and must not invent "
                "a TaskSpec, second plan, or training card."
            ),
        }
    live_plan = _live_formal_plan_for_task_mint(context)
    if live_plan is None:
        return {
            "ok": False,
            "error": "live_formal_plan_required",
            "detail": "No live learning plan is bound.",
        }
    runtime = context.runtime
    spec_service = getattr(runtime, "spec_service", None)
    if spec_service is None or not callable(getattr(spec_service, "specify", None)):
        return {"ok": False, "error": "service_unavailable", "detail": "spec_service is unavailable."}
    from ..core.models import TaskSpecifyRequest

    goal = " ".join(
        str(args.get("natural_language_goal") or args.get("goal") or args.get("message") or "").split()
    ).strip()
    if not goal:
        goal = " ".join(str((context.extra or {}).get("learner_message") or "").split()).strip()
    if not goal:
        return {
            "ok": False,
            "error": "goal_required",
            "detail": "Provide natural_language_goal so the task has a concrete objective.",
        }
    plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
    try:
        task = spec_service.specify(
            TaskSpecifyRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                natural_language_goal=goal,
            )
        )
        meta = dict(getattr(task, "metadata", None) or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        _persist_minted_task_on_sessions(context, task, live_plan)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {
        "ok": True,
        "committed": True,
        "task": task.model_dump(mode="json"),
        "plan_id": plan_id,
    }


async def _handle_next_task(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Mint next TaskSpec for a live-bound formal plan only (HTTP /task/next parity)."""
    if not _task_mint_tool_allowed(context):
        return {
            "ok": False,
            "error": "live_formal_plan_required",
            "detail": (
                "next_task requires a live-bound formal plan and must not invent "
                "a TaskSpec, second plan, or training card."
            ),
        }
    live_plan = _live_formal_plan_for_task_mint(context)
    if live_plan is None:
        return {
            "ok": False,
            "error": "live_formal_plan_required",
            "detail": "No live learning plan is bound.",
        }
    runtime = context.runtime
    planner_service = getattr(runtime, "planner_service", None)
    if planner_service is None or not callable(getattr(planner_service, "next_task", None)):
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "planner_service is unavailable.",
        }
    plan_id = str(getattr(live_plan, "id", "") or getattr(live_plan, "plan_id", "") or "").strip()
    focus = " ".join(str(args.get("focus_area") or args.get("focus") or "").split()).strip() or None
    memory = None
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is not None:
        try:
            memory = memory_service.snapshot(context.workspace_id)
        except Exception:
            memory = None
    try:
        task = planner_service.next_task(
            context.profile,
            focus_area=focus,
            current_plan=live_plan,
            memory_snapshot=memory,
            response_language=context.response_language,
        )
        meta = dict(getattr(task, "metadata", None) or {})
        meta["plan_id"] = plan_id
        task = task.model_copy(update={"metadata": meta})
        _persist_minted_task_on_sessions(context, task, live_plan)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {
        "ok": True,
        "committed": True,
        "task": task.model_dump(mode="json"),
        "plan_id": plan_id,
    }


# --- generate_training_card --------------------------------------------


_TOOL_TRAINING_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*[^\s,;]+"
)
_TOOL_TRAINING_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}")
_TOOL_TRAINING_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_TOOL_TRAINING_WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:/")


def _compact_tool_training_text(value: object, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].rstrip()


def _relative_tool_training_path(value: object, workspace_root: object) -> str:
    """Return a workspace-relative path suitable for persisted card copy."""

    path = _compact_tool_training_text(value, limit=480).replace("\\", "/")
    root = _compact_tool_training_text(workspace_root, limit=480).replace("\\", "/").rstrip("/")
    if (
        not path
        or "\x00" in path
        or path.startswith("<")
        or _TOOL_TRAINING_URI_PATTERN.match(path)
    ):
        return ""

    def normalized_parts(candidate: str) -> list[str] | None:
        parts: list[str] = []
        for part in candidate.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                return None
            parts.append(part)
        return parts

    path_parts = normalized_parts(path)
    if path_parts is None:
        return ""
    is_absolute = path.startswith("/") or bool(_TOOL_TRAINING_WINDOWS_PATH_PATTERN.match(path))
    if not is_absolute:
        return "/".join(path_parts)

    root_parts = normalized_parts(root)
    if not root_parts:
        return ""
    compare_casefold = bool(_TOOL_TRAINING_WINDOWS_PATH_PATTERN.match(root))
    comparable_path = [part.casefold() for part in path_parts] if compare_casefold else path_parts
    comparable_root = [part.casefold() for part in root_parts] if compare_casefold else root_parts
    if comparable_path[: len(comparable_root)] != comparable_root:
        return ""
    return "/".join(path_parts[len(root_parts) :])


def _redact_tool_training_diagnostic(value: object) -> str:
    diagnostic = _compact_tool_training_text(value, limit=360)
    diagnostic = _TOOL_TRAINING_SECRET_PATTERN.sub(r"\1=[redacted]", diagnostic)
    return _TOOL_TRAINING_BEARER_PATTERN.sub("Bearer [redacted]", diagnostic)


def _safe_tool_training_remote_name(value: object) -> str:
    remote_name = _compact_tool_training_text(value, limit=160)
    if not remote_name or "\x00" in remote_name or _TOOL_TRAINING_URI_PATTERN.match(remote_name):
        return ""
    return _redact_tool_training_diagnostic(remote_name)


def _tool_response_language(value: object) -> ResponseLanguage | None:
    language = str(value or "").strip()
    if language == "zh-CN":
        return "zh-CN"
    if language == "en-US":
        return "en-US"
    if language == "es-ES":
        return "es-ES"
    if language == "fr-FR":
        return "fr-FR"
    if language == "de-DE":
        return "de-DE"
    if language == "ja-JP":
        return "ja-JP"
    if language == "ko-KR":
        return "ko-KR"
    if language == "pt-BR":
        return "pt-BR"
    return None


def _tool_training_workspace_facts(context: ToolContext) -> dict[str, object]:
    """Project only safe, request-scoped facts into a generated training card."""

    current_file = context.extra.get("current_file") if isinstance(context.extra, dict) else None
    current_file = current_file if isinstance(current_file, dict) else {}
    runtime = context.runtime
    resolve_workspace_path = getattr(runtime, "resolve_workspace_path", None)
    workspace_root = ""
    if callable(resolve_workspace_path):
        try:
            workspace_root = str(resolve_workspace_path(context.workspace_id) or "")
        except Exception:
            workspace_root = ""

    current_path = _relative_tool_training_path(current_file.get("path"), workspace_root)
    language_id = _compact_tool_training_text(current_file.get("language_id"), limit=120)
    content = _compact_tool_training_text(current_file.get("content"), limit=12000)
    excerpt = _compact_tool_training_text(current_file.get("content_excerpt"), limit=4000)
    selection = _compact_tool_training_text(current_file.get("selection_text"), limit=4000)
    selection_range = _compact_tool_training_text(current_file.get("selection_range"), limit=120)
    raw_diagnostics = current_file.get("diagnostics")
    diagnostics = (
        [
            _redact_tool_training_diagnostic(item)
            for item in raw_diagnostics[:8]
            if _redact_tool_training_diagnostic(item)
        ]
        if isinstance(raw_diagnostics, list)
        else []
    )

    workspace = {}
    memory_service = getattr(runtime, "memory_service", None)
    snapshot = getattr(memory_service, "snapshot", None)
    if callable(snapshot):
        try:
            candidate = snapshot(context.workspace_id)
            workspace = getattr(candidate, "workspace", {})
        except Exception:
            workspace = {}
    workspace = workspace if isinstance(workspace, dict) else {}
    remote_name = _safe_tool_training_remote_name(workspace.get("remote_name"))
    remote_facts: list[str] = []
    if remote_name:
        remote_facts.append(f"remote identity: {remote_name}")
    if workspace_root:
        remote_facts.append("workspace root: .")
    if current_path:
        remote_facts.append(f"current file: {current_path}")

    return {
        "current_file_path": current_path,
        "current_file_language_id": language_id,
        "current_file_content": content,
        "current_file_excerpt": excerpt,
        "current_file_selection": selection,
        "current_file_selection_range": selection_range,
        "current_file_diagnostics": diagnostics,
        "workspace_root_path": "." if workspace_root else "",
        "remote_workspace_name": remote_name,
        "remote_workspace_facts": remote_facts,
    }


async def _handle_generate_training_card(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from ..core.models import ActiveCardSelectionResult, CardGenerationContext

    if not _explicit_training_card_request_allowed(context):
        return {
            "ok": False,
            "error": "explicit_training_card_request_required",
            "detail": "This write is only available when the learner explicitly asked to create a training card.",
        }
    runtime = context.runtime
    card_generation_service = getattr(runtime, "card_generation_service", None)
    if card_generation_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "card_generation_service is not registered on the runtime.",
        }
    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "memory_service is not registered on the runtime.",
        }
    # ReAct/composer must not mint or clobber. Explicit POST /training/generate-card binds.
    from ..memory.workspace_recovery import (  # noqa: F401 — keep import site for leftover helpers below
        PLAN_RUNTIME_KEY,
        leftover_training_handoff_chrome_is_not_live,
        select_plan_runtime_for_scope,
    )

    live_card_id = ""
    get_live = getattr(memory_service, "live_selected_training_card_id", None)
    if callable(get_live):
        live_card_id = str(get_live(context.workspace_id) or "").strip()
    if live_card_id:
        return {
            "ok": False,
            "error": "live_card_already_selected",
            "detail": (
                "A live training card is already selected; chat will not invent a second card. "
                "Use POST /training/generate-card only when intentionally replacing."
            ),
            "selected_card_id": live_card_id,
        }
    # Empty B or leftover-not-live: chat cannot invent. HTTP generate-card remains the binder.
    _ = (PLAN_RUNTIME_KEY, leftover_training_handoff_chrome_is_not_live, select_plan_runtime_for_scope)
    return {
        "ok": False,
        "error": "explicit_http_generate_card_required",
        "detail": (
            "Chat cannot mint a training card without a live selected_card_id. "
            "Use POST /training/generate-card to bind a new live card."
        ),
    }
    snapshot = memory_service.snapshot(context.workspace_id)
    workspace = snapshot.workspace if isinstance(snapshot.workspace, dict) else {}
    plan_runtime = select_plan_runtime_for_scope(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        context.workspace_id,
    ) or {}
    repository = getattr(runtime, "repository", None)
    leftover_plan = repository.get_latest_plan(context.workspace_id) if repository is not None else None
    # Recovered leftover-not-live without live card id: do not invent from title.
    # Explicit POST /training/generate-card remains the leftover binder.
    if (
        plan_runtime
        and not live_card_id
        and leftover_training_handoff_chrome_is_not_live(
            runtime=plan_runtime,
            existing=plan_runtime,
            plan=leftover_plan,
        )
    ):
        return {
            "ok": False,
            "error": "leftover_not_live_card",
            "detail": (
                "generate_training_card must not invent from leftover title or "
                "current_step. Use POST /training/generate-card to bind a new live card."
            ),
        }
    focus = str(args.get("focus_area") or args.get("focus") or "").strip()
    requested_card_type = str(args.get("card_type") or "practice").strip().lower()
    card_type: Literal["flash", "practice"] = (
        "flash" if requested_card_type == "flash" else "practice"
    )
    target_skill = str(args.get("target_skill") or focus or "").strip()
    why_now = str(args.get("why_now") or "").strip()
    if not focus and not target_skill:
        return {
            "ok": False,
            "error": "missing_focus",
            "detail": "Provide focus_area or target_skill so the card has a clear teaching objective.",
        }
    generate_card = getattr(card_generation_service, "generate_card", None)
    if not callable(generate_card):
        return {
            "ok": False,
            "error": "unsupported",
            "detail": "Card generation service has no compatible generate_card method.",
        }
    generation_context = CardGenerationContext(
        workspace_id=context.workspace_id,
        source="conversation_gap",
        card_type=card_type,
        focus_area=focus or target_skill,
        target_skill=target_skill or focus,
        why_now=why_now,
        response_language=_tool_response_language(context.response_language),
    ).model_copy(update=_tool_training_workspace_facts(context))
    from ..memory.workspace_recovery import (
        CURRENT_TASK_KEY,
        apply_live_training_mint_to_card,
        formal_plan_is_live_runtime_identity,
        formal_task_is_live_runtime_identity,
        leftover_formal_training_labels,
        live_training_mint_anchors,
        live_training_why_this_card,
        normalize_latest_current_task,
    )

    plan = leftover_plan
    task = normalize_latest_current_task(
        workspace.get(CURRENT_TASK_KEY)
        or workspace.get("current_task")
        or workspace.get("currentTask"),
        context.workspace_id,
    ) or {}
    task_title = str(task.get("title") or "").strip()
    recovered_step = str(plan_runtime.get("current_step") or "").strip()
    mint_anchors = live_training_mint_anchors(
        plan=plan,
        runtime=plan_runtime,
        existing=plan_runtime,
        task_title=task_title,
        why_now=generation_context.why_now,
        target_skill=generation_context.target_skill,
        focus_area=generation_context.focus_area,
    )
    generation_context = generation_context.model_copy(update=mint_anchors)
    leftover_labels = leftover_formal_training_labels(
        plan=plan,
        task_title=task_title,
        live_plan=formal_plan_is_live_runtime_identity(
            plan=plan,
            runtime=plan_runtime,
            existing=plan_runtime,
            current_step=recovered_step,
        ),
        live_task=formal_task_is_live_runtime_identity(
            recovered=bool(plan_runtime),
            runtime_current_step=recovered_step,
            task_title=task_title,
        ),
    )
    try:
        result = generate_card("conversation_gap", generation_context)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    result = apply_live_training_mint_to_card(
        result,
        anchors=mint_anchors,
        leftover_labels=leftover_labels,
        recovered_step=recovered_step,
    )
    stored_card = memory_service.upsert_card(context.workspace_id, result)

    def _tool_plan_state() -> dict[str, Any]:
        leftover_fields: dict[str, Any] = {
            "leftover_plan": plan,
            "leftover_runtime": plan_runtime if isinstance(plan_runtime, dict) else {},
            "leftover_task_title": task_title,
        }
        repository = getattr(runtime, "repository", None)
        if repository is None or not hasattr(repository, "get_latest_plan"):
            return leftover_fields
        latest_plan = repository.get_latest_plan(context.workspace_id)
        if latest_plan is None:
            return leftover_fields
        leftover_fields["leftover_plan"] = latest_plan
        active_stage = next(
            (
                stage
                for stage in latest_plan.stages
                if stage.id == latest_plan.current_stage_id or stage.status == "active"
            ),
            latest_plan.stages[0] if latest_plan.stages else None,
        )
        if active_stage is None:
            return leftover_fields
        return {
            "active_stage_id": active_stage.id,
            "active_stage_skills": [item for item in active_stage.outcomes if item],
            "active_project_id": context.workspace_id,
            **leftover_fields,
        }

    def _tool_learner_state() -> dict[str, Any]:
        snapshot = memory_service.snapshot(context.workspace_id)
        workspace = snapshot.workspace if isinstance(snapshot.workspace, dict) else {}
        recent_errors: list[str] = []
        for item in list(snapshot.learning_outcomes)[-6:]:
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

        overrides = routing_learner_overrides(controls_from_profile(snapshot.coaching_adaptation))
        transfer = normalize_transfer_skill_state_record(workspace.get("latest_transfer_state"))
        adaptation = snapshot.coaching_adaptation
        scene_count = int(getattr(adaptation, "transfer_scene_count", 0) or 0) if adaptation is not None else 0
        if transfer and int(transfer.get("scene_count") or 0) > scene_count:
            scene_count = int(transfer.get("scene_count") or 0)
        return {
            "weaknesses": list(snapshot.weaknesses or []),
            "recent_errors": recent_errors,
            "difficulty_preference": overrides["difficulty_preference"],
            "needs_rescue": bool(overrides["needs_rescue"]) or needs_rescue,
            "active_blockers": [blocker_focus] if blocker_focus and needs_rescue else [],
            "material_recommendation": overrides.get("material_recommendation"),
            "transfer_scene_count": scene_count,
            "transfer_state": str((transfer or {}).get("state") or ""),
            "time_budget": overrides.get("time_budget"),
            "project_complexity": overrides.get("project_complexity"),
            "task_urgency": overrides.get("task_urgency"),
        }

    selection = ActiveCardSelectionResult(
        selected_card=stored_card,
        selected_card_id=stored_card.card_id,
        selection_score=100.0,
        why_this_card=live_training_why_this_card(
            plan=plan,
            runtime=plan_runtime,
            existing=plan_runtime,
            task_title=task_title,
            card_title=stored_card.title,
            why_now=stored_card.why_now,
            kind="current",
        )
        or "This is the current training card.",
        fallback_action="Return to coach with the exact blocker and verification output.",
        next_after_completion="Update evidence, then route the next card.",
        candidate_count=1,
        eligible_count=1,
    )
    router_service = getattr(runtime, "card_router_service", None)
    if router_service is not None:
        routed = router_service.select_active_card(
            memory_service.get_cards(context.workspace_id),
            _tool_learner_state(),
            _tool_plan_state(),
        )
        selection = memory_service.persist_active_card_selection(context.workspace_id, routed)
    else:
        selection = memory_service.persist_active_card_selection(context.workspace_id, selection)
    sandbox_service = getattr(runtime, "sandbox_service", None)
    if sandbox_service is not None:
        try:
            sandbox_service.persist_training_card(
                context.workspace_id,
                selection.selected_card or stored_card,
                mark_current=True,
                leftover_plan=plan,
                leftover_runtime=plan_runtime if isinstance(plan_runtime, dict) else {},
                leftover_task_title=task_title,
            )
        except Exception:
            logger.exception(
                "Failed to persist generated training card into Trainer sandbox.",
                extra={"workspace_id": context.workspace_id, "card_id": stored_card.card_id},
            )

    return {
        "ok": True,
        "card": stored_card.model_dump(mode="json"),
        "active_routing": selection.model_dump(mode="json"),
    }


# --- run_diagnostics ----------------------------------------------------

_LANGUAGE_HINTS = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}


async def _handle_run_diagnostics(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Quick static checks against a file: byte count, line count, simple
    structural lints. This is intentionally conservative — we never execute
    user code; we just give the agent grounded facts about the file."""
    path_raw = str(args.get("path") or "").strip()
    if not path_raw:
        return {"ok": False, "error": "missing_path"}
    root = _resolve_workspace_root(context)
    target = _safe_path_under(root, path_raw)
    if target is None or not target.is_file():
        return {"ok": False, "error": "not_found", "detail": f"{path_raw!r} is not a readable file."}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    suffix = target.suffix.lower()
    language = next((lang for lang, exts in _LANGUAGE_HINTS.items() if suffix in exts), None)
    line_count = text.count("\n") + (0 if text.endswith("\n") or text == "" else 1)
    findings: list[dict[str, Any]] = []
    # Trailing whitespace
    trailing_ws = sum(1 for line in text.splitlines() if line != line.rstrip())
    if trailing_ws:
        findings.append({"kind": "style", "detail": f"{trailing_ws} lines with trailing whitespace"})
    # Tabs vs spaces (Python only)
    if language == "python" and "\t" in text:
        findings.append({"kind": "style", "detail": "file mixes tabs and spaces"})
    # TODO/FIXME
    todo_count = len(re.findall(r"\b(TODO|FIXME)\b", text))
    if todo_count:
        findings.append({"kind": "note", "detail": f"{todo_count} TODO/FIXME comments"})
    # Long lines
    long_lines = [idx + 1 for idx, line in enumerate(text.splitlines()) if len(line) > 120]
    if long_lines:
        findings.append({"kind": "style", "detail": f"{len(long_lines)} lines longer than 120 chars"})
    return {
        "ok": True,
        "path": str(target.relative_to(root)) if root is not None else str(target),
        "language": language,
        "line_count": line_count,
        "byte_size": len(text.encode("utf-8", errors="replace")),
        "findings": findings,
    }


# --- coach_finalize -----------------------------------------------------


async def _handle_coach_finalize(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Sentinel tool the model can call to declare the turn finished and pass a
    short summary back to the human-facing assistant message. The agent loop
    treats this as a stop signal."""
    summary = str(args.get("summary") or args.get("decision") or "").strip()
    next_step = str(args.get("next_step") or "").strip()
    blocker = str(args.get("blocker") or "").strip()
    teaching_note = str(args.get("teaching_note") or "").strip()
    resume_thread = str(args.get("resume_thread") or "").strip()
    confidence = str(args.get("confidence") or "").strip()
    evidence = [
        str(item).strip()
        for item in args.get("evidence", [])
        if isinstance(item, str) and str(item).strip()
    ] if isinstance(args.get("evidence"), list) else []
    return {
        "ok": True,
        "final": True,
        "summary": summary or None,
        "next_step": next_step or None,
        "decision": str(args.get("decision") or "").strip() or None,
        "blocker": blocker or None,
        "teaching_note": teaching_note or None,
        "resume_thread": resume_thread or None,
        "confidence": confidence or None,
        "evidence": evidence or None,
    }


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def build_default_tool_registry() -> ToolRegistry:
    """Return the default registry used by Trainer's coach agent loop."""
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="search_resources",
            description=(
                "Search the learner's resource library (papers, code, notes) "
                "for material relevant to the current question. Use this "
                "before claiming a resource exists or to ground references. "
                "Use mode='broad' to map the space, mode='narrow' to sharpen "
                "one mechanism, and mode='verify' to prefer citation-ready hits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": _string("Free-text search query."),
                    "mode": _enum(
                        "Search phase to run: broad maps candidates, narrow sharpens one mechanism, verify prefers grounded evidence.",
                        ["broad", "narrow", "verify"],
                    ),
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of hits (1-12).",
                        "minimum": 1,
                        "maximum": 12,
                        "default": 5,
                    },
                    "project_scope": _string("Optional project scope filter."),
                    "trust_state": _string("Optional trust-state filter such as trusted or blocked."),
                    "file_type": _string("Optional file-type filter."),
                    "source_type": _string("Optional source-type filter."),
                    "kind": _string("Optional resource kind filter."),
                    "index_state": _string("Optional index-state filter such as indexed."),
                },
                "required": ["query"],
            },
            handler=_handle_search_resources,
        )
    )

    registry.register(
        ToolDefinition(
            name="import_resource_url",
            description=(
                "Import one explicitly requested public HTTP(S) URL into the "
                "Resources library. Use only in a Resources turn whose "
                "resource_composer_intent.mode is download. The tool performs "
                "controlled ingestion through ResourceService, preserves source "
                "provenance and failure status, and never moves or deletes local files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": _string("Public HTTP(S) URL to import after the learner explicitly requests a download."),
                    "name": _string("Optional display name for the imported source."),
                    "tags": _string_array("Optional tags to attach to the imported source."),
                },
                "required": ["url"],
            },
            handler=_handle_import_resource_url,
        )
    )

    registry.register(
        ToolDefinition(
            name="organize_resources",
            description=(
                "Propose or execute a small, reversible Resources-library organization inside "
                "Trainer's managed sandbox. Supported operations are mkdir, move, rename, and "
                "delete (a resource_id may be used to move its synced artifact). Calls without "
                "host confirmation return a dry proposal only. Filesystem changes require the "
                "host to stamp resource_organization_confirmed after the learner reviews the "
                "paths — never self-attest via tool arguments. A successful commit returns "
                "history_id and undo_operations so the change can be reversed with undo_id. "
                "Never touches the user's source workspace or performs network operations."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "description": "Ordered sandbox organization operations.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": _enum(
                                    "Operation kind. Restore is reserved for undo flows.",
                                    ["mkdir", "move", "rename", "delete", "restore"],
                                ),
                                "path": _string("Sandbox-relative path for mkdir/delete or the move source."),
                                "source": _string("Sandbox-relative source path for move/rename."),
                                "target": _string("Sandbox-relative destination path for move/rename."),
                                "new_path": _string("Alias for target."),
                                "resource_id": _string("Optional resource id whose synced sandbox artifact is the source."),
                            },
                            "required": ["op"],
                        },
                    },
                    "undo_id": _string(
                        "History id returned by a prior commit; reverses that commit after host confirmation."
                    ),
                },
            },
            handler=_handle_organize_resources,
        )
    )

    registry.register(
        ToolDefinition(
            name="list_sandbox",
            description=(
                "List files and folders inside Trainer's managed resource sandbox. "
                "This is the library working tree, never the learner's project root. "
                "Use it before reading, editing, or indexing sandbox notes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum entries to return (1-200).",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 80,
                    },
                },
            },
            handler=_handle_list_sandbox,
        )
    )

    registry.register(
        ToolDefinition(
            name="read_sandbox_file",
            description=(
                "Read a file or directory listing from Trainer's managed resource sandbox. "
                "Path must be sandbox-relative. Never use this to read the learner's project."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Sandbox-relative path to preview."),
                    "max_chars": {
                        "type": "integer",
                        "description": "Truncate file content to this many characters (64-32000).",
                        "minimum": 64,
                        "maximum": 32000,
                        "default": 8000,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_read_sandbox_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="write_sandbox_file",
            description=(
                "Create or overwrite a text file inside Trainer's managed resource sandbox. "
                "Use this to edit library notes, extracted artifacts, and working copies. "
                "Never write the learner's project or business code. Parent folders are created."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Sandbox-relative path to write."),
                    "content": _string("Full file contents to write."),
                    "create": {
                        "type": "boolean",
                        "description": "Create the file when missing. Defaults to true.",
                        "default": True,
                    },
                },
                "required": ["path", "content"],
            },
            handler=_handle_write_sandbox_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="index_sandbox_file",
            description=(
                "Register or reindex a sandbox file in the Resources library so search can find it. "
                "Use after writing or editing a sandbox note. Does not touch the learner's project."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Sandbox-relative path to register or reindex."),
                    "name": _string("Optional display name for a newly registered resource."),
                    "tags": _string_array("Optional tags for a newly registered resource."),
                },
                "required": ["path"],
            },
            handler=_handle_index_sandbox_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="inspect_current_file",
            description=(
                "Read the active IDE file snapshot that VS Code attached to "
                "this turn, including current content, selection, and recent "
                "diagnostics. Use this before evaluating a hands-on practice "
                "answer or when the learner says 'this file' without naming a path."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "max_chars": {
                        "type": "integer",
                        "description": "Truncate current file and selection content to this many characters (64-32000).",
                        "minimum": 64,
                        "maximum": 32000,
                        "default": 8000,
                    },
                },
            },
            handler=_handle_inspect_current_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="verify_practice_current_file",
            description=(
                "Verify a hands-on training practice against the active IDE "
                "file snapshot and VS Code diagnostics. This does not edit or "
                "execute the learner's code. It returns passed, needs_review, "
                "or blocked with concrete evidence, and must be used before "
                "claiming a practice card passed from current-file work."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "acceptance_criteria": _string_array(
                        "Concrete practice acceptance criteria to check against the active file."
                    ),
                    "expected_symbols": _string_array(
                        "Specific symbols, APIs, selectors, functions, or text signals expected in the file."
                    ),
                    "allow_warnings": {
                        "type": "boolean",
                        "description": "If true, warning diagnostics do not prevent a passed result.",
                        "default": False,
                    },
                    "training_card_id": _string(
                        "Optional active practice card id; used only to attach verification evidence to the training ledger."
                    ),
                    "training_card_title": _string(
                        "Optional active practice card title for evidence recovery."
                    ),
                    "focus_area": _string(
                        "Optional learning focus area for the persisted practice evidence."
                    ),
                    "max_evidence": {
                        "type": "integer",
                        "description": "Maximum evidence bullets to return (1-20).",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 8,
                    },
                },
            },
            handler=_handle_verify_practice_current_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="read_workspace_file",
            description=(
                "Read the text content of a file inside the active workspace. "
                "Path must be inside the workspace root. Use to ground claims "
                "about the learner's actual code, not to write or modify it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Workspace-relative or absolute path inside the workspace."),
                    "max_chars": {
                        "type": "integer",
                        "description": "Truncate content to this many characters (64-16000).",
                        "minimum": 64,
                        "maximum": 16000,
                        "default": 4000,
                    },
                },
                "required": ["path"],
            },
            handler=_handle_read_workspace_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="list_workspace_files",
            description=(
                "Glob files in the active workspace. Use sparingly to discover "
                "files the learner mentioned but did not pin in context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": _string("Glob pattern relative to workspace root.", default="**/*"),
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (1-200).",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 30,
                    },
                },
            },
            handler=_handle_list_workspace_files,
        )
    )

    registry.register(
        ToolDefinition(
            name="import_workspace_file",
            description=(
                "Copy one learner-project file into Trainer's local resource library. "
                "Use this to download remote or local workspace code into the sandbox "
                "for teaching, notes, and search. Never writes back to the learner's project."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Workspace-relative path of the file to copy into the library."),
                },
                "required": ["path"],
            },
            handler=_handle_import_workspace_file,
        )
    )

    registry.register(
        ToolDefinition(
            name="recall_memory",
            description=(
                "Read the structured coach memory for this workspace: current "
                "focus, due reviews, recent learning outcomes, observations, "
                "saved preferences. Use before generating a plan or card."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "focus": _string("Optional focus topic to narrow the snapshot."),
                },
            },
            handler=_handle_recall_memory,
        )
    )

    registry.register(
        ToolDefinition(
            name="record_learning_note",
            description=(
                "Persist a teaching observation, blocker, or decision into "
                "long-term memory for this workspace so future turns can "
                "build on it. Use when the learner reveals something durable."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "note": _string("The observation to remember (1-2 sentences)."),
                    "kind": _enum(
                        "Category of note.",
                        ["observation", "blocker", "decision", "preference"],
                    ),
                },
                "required": ["note"],
            },
            handler=_handle_record_learning_note,
            coach_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="inspect_plan",
            description=(
                "Read the active learning plan and its stages, including the "
                "currently active stage and the next step. Use before "
                "proposing changes to the plan."
            ),
            parameters={"type": "object", "properties": {}},
            handler=_handle_inspect_plan,
        )
    )

    registry.register(
        ToolDefinition(
            name="save_formal_plan",
            description=(
                "Commit the formal learning plan after the learner's current "
                "request and available library evidence have been understood. "
                "Use only on an explicit formal plan-generation turn; ask a "
                "clarifying question instead when the goal, time budget, or "
                "evidence is still ambiguous."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": _string("Short plan title."),
                    "summary": _string("The learner-facing objective and rationale."),
                    "cadence": _string("Weekly cadence or time-box, if agreed."),
                    "current_step": _string("The first small step the learner can do now."),
                    "why_now": _string("Why the first stage is the right next move."),
                    "verify_method": _string_array("Concrete checks that prove progress."),
                    "blocked_reason": _string("Known blocker, if one remains."),
                    "next_after_current": _string("What happens after the active stage is verified."),
                    "stages": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": _string("Stable stage identifier."),
                                "title": _string("Stage title."),
                                "goal": _string("Concrete stage goal."),
                                "outcomes": _string_array("Observable outcomes."),
                                "resources": _string_array("Resource IDs or evidence labels used by this stage."),
                                "status": _enum("Stage status.", ["pending", "active", "completed"]),
                            },
                            "required": ["title", "goal"],
                        },
                    },
                },
                "required": ["title", "summary", "stages"],
            },
            handler=_handle_save_formal_plan,
            coach_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="specify_task",
            description=(
                "Turn a natural-language goal into a TaskSpec bound to the live "
                "formal plan. Use only when a live plan is already bound; never "
                "invent a plan, TaskSpec, or training card without one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "natural_language_goal": _string(
                        "Concrete coding goal to turn into a TaskSpec."
                    ),
                },
                "required": ["natural_language_goal"],
            },
            handler=_handle_specify_task,
            coach_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="next_task",
            description=(
                "Propose the next TaskSpec on the live formal plan. Use only when "
                "a live plan is already bound; never invent a plan or TaskSpec "
                "without one."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "focus_area": _string("Optional focus area for the next task."),
                },
            },
            handler=_handle_next_task,
            coach_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="generate_training_card",
            description=(
                "Generate a new training card (flash recall or hands-on "
                "practice) targeting a specific weak spot. The card lands in "
                "the learner's training queue. Use only when the learner "
                "explicitly asked to create or generate a training card; never "
                "mint a card on a normal coach, understand, diagnose, or "
                "learn-first turn."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "focus_area": _string("Focus topic the card will exercise."),
                    "target_skill": _string("Specific skill or API to recall/apply."),
                    "card_type": _enum(
                        "Type of card to generate.",
                        ["flash", "practice"],
                    ),
                    "why_now": _string("One sentence on why this card is appropriate now."),
                },
                "required": ["focus_area"],
            },
            handler=_handle_generate_training_card,
            coach_only=True,
        )
    )

    registry.register(
        ToolDefinition(
            name="run_diagnostics",
            description=(
                "Run lightweight static checks (line count, trailing whitespace, "
                "TODO comments, long lines, language hint) on a workspace file. "
                "Does NOT execute the user's code."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": _string("Workspace-relative path to inspect."),
                },
                "required": ["path"],
            },
            handler=_handle_run_diagnostics,
        )
    )

    registry.register(
        ToolDefinition(
            name="coach_finalize",
            description=(
                "Signal the end of the agent's tool-calling phase. Use it "
                "last, once you already have enough evidence to close the "
                "turn. Provide a short summary and a concrete next step, and "
                "add grounded decision, blocker, teaching note, confidence, "
                "resume thread, or evidence bullets when they will help the learner resume."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": _string("Short summary of what was investigated or decided this turn."),
                    "next_step": _string("Concrete next step the learner should take next."),
                    "decision": _string("Short conclusion or decision the coach reached."),
                    "blocker": _string("Remaining blocker or unresolved issue, if any."),
                    "teaching_note": _string("One short teaching note to remember from this turn."),
                    "resume_thread": _string("One short sentence that tells the next turn how to resume."),
                    "confidence": _enum("Confidence in the final conclusion.", ["low", "medium", "high"]),
                    "evidence": _string_array("Short, grounded evidence bullets that support the conclusion."),
                },
                "required": ["summary", "next_step"],
            },
            handler=_handle_coach_finalize,
        )
    )

    return registry


__all__ = [
    "JsonSchema",
    "ToolContext",
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "build_default_tool_registry",
]
