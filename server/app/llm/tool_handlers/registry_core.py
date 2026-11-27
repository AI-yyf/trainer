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
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, cast

logger = logging.getLogger("trainer.llm.tools")



def _prefers_chinese(language: str | None) -> bool:
    return bool((language or "").strip().lower().startswith("zh"))


PROJECT_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    "write_file",
    "apply_patch",
    "edit_file",
    "insert_code",
    "execute_command",
    "run_command",
})


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
        explicit_lecture_note_save_request: bool = False,
        explicit_resource_import: bool = False,
        explicit_resource_organize: bool = False,
        live_formal_plan_for_task_mint: bool = False,
        orthogonal_only: bool = False,
        stabilize_orthogonal_schema: bool = False,
    ) -> list[dict[str, Any]]:
        allowed = _tool_name_allowlist(allowed_tool_names)
        if allowed is not None and len(allowed) == 0:
            return []
        if orthogonal_only and allowed is None:
            from ..tool_primitives import ORTHOGONAL_PRIMITIVE_SET

            allowed = set(ORTHOGONAL_PRIMITIVE_SET)
        denied = _tool_name_allowlist(denied_tool_names) or set()
        # Learning OS: never expose project/business-code writers to the coach agent.
        denied.update(PROJECT_WRITE_TOOL_NAMES)
        # Composer chat / ReAct never mints; POST /training/generate-card binds ids.
        denied.add("generate_training_card")
        _ = (explicit_training_card_request, explicit_resource_import, explicit_resource_organize)
        if formal_plan_mutation is not True:
            denied.add("save_formal_plan")
        if explicit_learning_note_request is not True:
            denied.add("record_learning_note")
        if (
            explicit_lecture_note_save_request is not True
            and explicit_learning_note_request is not True
        ):
            denied.add("save_lecture_note")
        if live_formal_plan_for_task_mint is not True:
            denied.add("specify_task")
            denied.add("next_task")

        if stabilize_orthogonal_schema and allowed:
            from ..tool_primitives import ORTHOGONAL_PRIMITIVE_NAMES, ORTHOGONAL_PRIMITIVE_SET

            if allowed.issubset(ORTHOGONAL_PRIMITIVE_SET) and all(
                self._tools.get(prim) is not None for prim in ORTHOGONAL_PRIMITIVE_NAMES
            ):
                # Emit the fixed 8-primitive schema array in canonical order across all
                # orthogonal tool-enabled turns & steps so Prefix KV Cache stays byte-invariant,
                # while ToolRegistry.invoke enforces per-turn allowed/denied gates fail-closed.
                stable_schemas = [
                    self._tools[prim].schema_for(protocol)
                    for prim in ORTHOGONAL_PRIMITIVE_NAMES
                ]
                for tool in self._tools.values():
                    if (
                        tool.name.startswith("mcp_")
                        and (allow_coach_only or not tool.coach_only)
                        and tool.name not in denied
                    ):
                        stable_schemas.append(tool.schema_for(protocol))
                return stable_schemas

        return [
            tool.schema_for(protocol)
            for tool in self._tools.values()
            if (allow_coach_only or not tool.coach_only)
            and (
                allowed is None
                or tool.name in allowed
                or (bool(allowed) and tool.name.startswith("mcp_"))
            )
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
        if allowed is not None and name not in allowed and not (bool(allowed) and name.startswith("mcp_")):
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
        if name == "run_rubric_review" and not _rubric_review_allowed(context):
            return {
                "ok": False,
                "error": "rubric_review_not_allowed",
                "detail": (
                    "run_rubric_review is only available in a host-gated practice "
                    "turn with a card rubric attached; it never runs speculatively."
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
        if name == "save_lecture_note" and not _explicit_lecture_note_save_allowed(context):
            return {
                "ok": False,
                "error": "explicit_lecture_note_save_required",
                "detail": (
                    "save_lecture_note is only available when the learner "
                    "explicitly asked to save a lecture or study note into their library."
                ),
            }
        parsed_arguments = _coerce_arguments(arguments)
        from ..harness import (
            invalidate_sandbox_operations,
            lookup_sandbox_operation,
            sandbox_operation_key,
            store_sandbox_operation,
        )

        operation_key = sandbox_operation_key(context.workspace_id, name, parsed_arguments)
        stateful_research_tool = name in {
            "search_learning_materials",
            "assess_research_evidence",
        } or (
            name == "web_fetch"
            and str(parsed_arguments.get("action") or "").strip().lower()
            in {"learning_materials", "assess_evidence"}
        )
        expected_path = (
            str(parsed_arguments.get("path") or "").strip() or None
            if isinstance(parsed_arguments, dict)
            else None
        )
        raw_expected_content = (
            parsed_arguments.get("content") if isinstance(parsed_arguments, dict) else None
        )
        expected_content = (
            raw_expected_content if isinstance(raw_expected_content, str) else None
        )
        if not stateful_research_tool:
            cached = lookup_sandbox_operation(
                context.runtime,
                operation_key,
                workspace_id=context.workspace_id,
                expected_path=expected_path,
                expected_content=expected_content,
            )
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
            if not stateful_research_tool:
                if operation_key is not None:
                    store_sandbox_operation(context.runtime, operation_key, result)
                elif result.get("ok") is True and name in {
                    "library_write",
                    "library_exec",
                    "organize_resources",
                    "curate_library_resources",
                    "delete_resource",
                    "restore_resource",
                    "save_lecture_note",
                    "import_resource_url",
                    "import_workspace_file",
                    "index_sandbox_file",
                }:
                    invalidate_sandbox_operations(context.runtime, context.workspace_id)
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
    from ...training.card_request import message_requests_explicit_training_card

    return message_requests_explicit_training_card(extra.get("learner_message"))


def _formal_plan_mutation_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("formal_plan_mutation") is True


def _rubric_review_allowed(context: ToolContext) -> bool:
    """Host-gated rubric review (P2 #15): same explicit-flag pattern as the
    formal-plan write gate. The host sets this only when the turn carries a
    practice verification context with a card rubric, so the coach cannot run
    rubric reviews speculatively in ordinary chat."""
    extra = context.extra if isinstance(context.extra, dict) else {}
    return extra.get("rubric_review_allowed") is True


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
    from ...memory.workspace_recovery import leftover_formal_plan_is_live_for_fill

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
    from ...memory.workspace_recovery import stamp_produced_workspace_record

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
    from ...memory.note_request import message_requests_explicit_learning_note

    return message_requests_explicit_learning_note(extra.get("learner_message"))


def _explicit_lecture_note_save_allowed(context: ToolContext) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    if extra.get("explicit_lecture_note_save_request") is True or extra.get("explicit_learning_note_request") is True:
        return True
    from ...memory.note_request import (
        message_requests_explicit_learning_note,
        message_requests_lecture_note_save,
    )

    learner_message = extra.get("learner_message")
    return message_requests_lecture_note_save(learner_message) or message_requests_explicit_learning_note(
        learner_message
    )


def resource_write_explicitly_requested(extra: dict[str, Any] | None, *, mode: str) -> bool:
    payload = extra if isinstance(extra, dict) else {}
    active_view = str(payload.get("active_view") or "").strip().lower()
    intent = payload.get("resource_composer_intent")
    model_dump = getattr(intent, "model_dump", None)
    if callable(model_dump):
        try:
            intent = model_dump()
        except Exception as exc:
            logger.debug("Suppressed exception in registry_core: %s", exc)
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
    except Exception as exc:
        logger.debug("Suppressed exception in registry_core: %s", exc)
        workspace_path = None
    if workspace_path is None:
        return None
    raw = str(workspace_path).strip()
    if not raw or "://" in raw:
        return None
    try:
        root = Path(raw).expanduser().resolve()
    except Exception as exc:
        logger.debug("Suppressed exception in registry_core: %s", exc)
        return None
    if not root.exists() or not root.is_dir():
        return None
    return root


def _safe_path_under(root: Path | None, candidate: str) -> Path | None:
    if not candidate:
        return None
    try:
        target = Path(candidate).expanduser()
    except Exception as exc:
        logger.debug("Suppressed exception in registry_core: %s", exc)
        return None
    if not target.is_absolute() and root is not None:
        target = root / target
    try:
        target = target.resolve()
    except Exception as exc:
        logger.debug("Suppressed exception in registry_core: %s", exc)
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
            leftover_plan, leftover_runtime, leftover_task_title = cast(
                "tuple[Any, dict[str, Any], str]", leftover_ctx(context.workspace_id)
            )
        except Exception as exc:
            logger.debug("Suppressed exception in registry_core: %s", exc)
            leftover_plan, leftover_runtime, leftover_task_title = None, {}, ""
        else:
            return (
                leftover_plan,
                leftover_runtime if isinstance(leftover_runtime, dict) else {},
                str(leftover_task_title or "").strip(),
            )
    from ...memory.workspace_recovery import (
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
    except Exception as exc:
        logger.debug("Suppressed exception in registry_core: %s", exc)
        return leftover_plan, leftover_runtime, leftover_task_title
    return leftover_plan, leftover_runtime, leftover_task_title
