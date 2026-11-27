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

import inspect
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Literal, cast
from uuid import uuid4

from ...core.models import (
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
from .registry_core import (
    ToolContext,
    resource_write_explicitly_requested,
)
from .search_and_research import (
    _resource_model_payload,
)

logger = logging.getLogger("trainer.llm.tools")


async def _handle_list_resources(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    repository = getattr(context.runtime, "repository", None)
    list_resources = getattr(repository, "list_resources", None)
    if not callable(list_resources):
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The resource library is not attached to this run.",
        }
    try:
        resources = list(cast("Iterable[Any]", list_resources(context.workspace_id)) or [])
    except Exception as exc:
        return {"ok": False, "error": "resource_list_failed", "detail": str(exc)}

    query = str(args.get("query") or "").strip().casefold()
    raw_limit = args.get("limit")
    limit_value = raw_limit if isinstance(raw_limit, (int, str)) else 40
    try:
        limit = max(1, min(int(limit_value), 100))
    except (TypeError, ValueError):
        limit = 40
    rows: list[dict[str, Any]] = []
    for resource in resources:
        name = str(getattr(resource, "name", "") or "")
        summary = str(getattr(resource, "summary", "") or "")
        if query and query not in f"{name}\n{summary}".casefold():
            continue
        rows.append(
            {
                "resource_id": str(getattr(resource, "id", "") or ""),
                "name": name,
                "kind": str(getattr(resource, "kind", "") or ""),
                "parse_status": str(getattr(resource, "parse_status", "") or ""),
                "index_status": str(getattr(resource, "index_status", "") or ""),
                "source": str(getattr(resource, "source", "") or ""),
                "sandbox_path": str(getattr(resource, "sandbox_path", "") or ""),
                "summary": summary[:240],
                "tags": list(getattr(resource, "tags", []) or []),
            }
        )
        if len(rows) >= limit:
            break
    return {"ok": True, "count": len(rows), "resources": rows}


async def _handle_delete_resource(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(args.get("resource_id") or "").strip()
    if not resource_id:
        return {
            "ok": False,
            "error": "missing_resource_id",
            "detail": "delete_resource requires a resource_id.",
        }
    resource_service = getattr(context.runtime, "resource_service", None)
    if resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The resource library is not attached to this run.",
        }
    sandbox_service = getattr(context.runtime, "sandbox_service", None)
    try:
        result = resource_service.delete(
            context.workspace_id,
            resource_id,
            sandbox_service=sandbox_service,
        )
        if inspect.isawaitable(result):
            result = await result
    except KeyError:
        return {"ok": False, "error": "resource_not_found", "detail": "That resource is not in this workspace."}
    except PermissionError as exc:
        return {"ok": False, "error": "resource_delete_blocked", "detail": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": "resource_delete_failed", "detail": str(exc)}
    payload = result if isinstance(result, dict) else {}
    removed = bool(payload.get("removed"))
    return {
        "ok": removed,
        "resource_id": resource_id,
        "removed": removed,
        "recoverable": bool(payload.get("recoverable", True)),
        "detail": str(payload.get("detail") or ""),
    }


async def _handle_restore_resource(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(args.get("resource_id") or "").strip()
    if not resource_id:
        return {
            "ok": False,
            "error": "missing_resource_id",
            "detail": "restore_resource requires a resource_id.",
        }
    resource_service = getattr(context.runtime, "resource_service", None)
    if resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The resource library is not attached to this run.",
        }
    sandbox_service = getattr(context.runtime, "sandbox_service", None)
    try:
        result = resource_service.restore_resource(
            context.workspace_id,
            resource_id,
            sandbox_service=sandbox_service,
        )
        if inspect.isawaitable(result):
            result = await result
    except KeyError:
        return {"ok": False, "error": "resource_not_found", "detail": "That resource is not in the library Trash."}
    except Exception as exc:
        return {"ok": False, "error": "resource_restore_failed", "detail": str(exc)}
    payload = result if isinstance(result, dict) else {}
    restored = payload.get("resource")
    return {
        "ok": True,
        "resource_id": resource_id,
        "resource": _resource_model_payload(restored) if restored is not None else {},
        "reindex_required": bool(payload.get("reindex_required", True)),
    }


async def _handle_refresh_resource_index(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    resource_id = str(args.get("resource_id") or "").strip()
    if not resource_id:
        return {
            "ok": False,
            "error": "missing_resource_id",
            "detail": "refresh_resource_index requires a resource_id.",
        }
    resource_service = getattr(context.runtime, "resource_service", None)
    if resource_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The resource library is not attached to this run.",
        }
    try:
        indexed = resource_service.index(
            context.workspace_id,
            ResourceIndexRequest(
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                resource_id=resource_id,
                enable_network=args.get("enable_network") is not False,
            ),
        )
        if inspect.isawaitable(indexed):
            indexed = await indexed
    except KeyError:
        return {"ok": False, "error": "resource_not_found", "detail": "That resource is not in this workspace."}
    except Exception as exc:
        return {"ok": False, "error": "resource_index_failed", "detail": str(exc)}
    payload = _resource_model_payload(indexed)
    succeeded = (
        str(payload.get("index_status") or "").strip().lower() == "indexed"
        and str(payload.get("parse_status") or "").strip().lower() == "parsed"
    )
    return {
        "ok": succeeded,
        "resource_id": resource_id,
        "status": payload.get("index_status") or payload.get("parse_status") or "unknown",
        "resource": payload,
    }


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
    except (AttributeError, TypeError):
        pass
    return store


def _resource_organization_cancel_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_cancel_requested", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_cancel_requested = store
    except (AttributeError, TypeError):
        pass
    return store


def _resource_organization_in_flight_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_in_flight", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_in_flight = store
    except (AttributeError, TypeError):
        pass
    return store


def _resource_organization_committed_store(runtime: Any) -> dict[str, Any]:
    store = getattr(runtime, "resource_organization_last_committed", None)
    if isinstance(store, dict):
        return store
    store = {}
    try:
        runtime.resource_organization_last_committed = store
    except (AttributeError, TypeError):
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
        for resource in cast("Iterable[Any]", list_resources(workspace_id)):
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
        resources = cast("Iterable[Any] | None", list_resources(workspace_id))
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
        except (OSError, ValueError, RuntimeError):
            pass
        if sandbox_root is not None:
            try:
                resolved = Path(sandbox_path)
                if not resolved.is_absolute():
                    resolved = sandbox_root / sandbox_path
                resolved = resolved.resolve()
                keys.add(_normalize_sandbox_path_key(str(resolved)))
                keys.add(_normalize_sandbox_path_key(resolved.relative_to(sandbox_root).as_posix()))
            except (OSError, ValueError, RuntimeError):
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
        if isinstance(history, dict):
            history.pop(undo_id, None)
            history[undo_id] = stored
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
                    explicitDestructivePolicy=True,
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
                        explicitDestructivePolicy=True,
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
                        explicitDestructivePolicy=True,
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
                        explicitDestructivePolicy=True,
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
            sessions_refreshed = int(
                cast("int", refresh_sessions(context.workspace_id)) or 0
            ) if callable(refresh_sessions) else 0
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
            history.pop(history_id, None)
            history[history_id] = {
                "workspace_id": context.workspace_id,
                "undo_operations": undo_operations,
            }
            while len(history) > 64:
                history.pop(next(iter(history)), None)
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
        sessions_refreshed = int(
            cast("int", refresh_sessions(context.workspace_id)) or 0
        ) if callable(refresh_sessions) else 0
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
    payload: dict[str, Any]
    if hasattr(preview, "model_dump") and callable(preview.model_dump):
        try:
            payload = cast("dict[str, Any]", preview.model_dump(mode="json"))
        except TypeError:
            payload = cast("dict[str, Any]", preview.model_dump())
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
        except Exception as exc:
            logger.debug("Indexed resource postprocess skipped for %s: %s", resource_id, exc)
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


def _slice_text_by_lines(
    text: str,
    *,
    start_line_raw: Any,
    end_line_raw: Any,
    max_chars: int,
) -> dict[str, Any]:
    lines = text.splitlines()
    total_lines = len(lines)
    has_line_window = start_line_raw is not None or end_line_raw is not None
    if has_line_window:
        try:
            start_line = max(1, int(start_line_raw)) if start_line_raw is not None else 1
        except (TypeError, ValueError):
            start_line = 1
        try:
            end_line = max(start_line, int(end_line_raw)) if end_line_raw is not None else total_lines
        except (TypeError, ValueError):
            end_line = total_lines
        selected = lines[start_line - 1 : end_line]
        joined = "\n".join(selected)
        truncated = len(joined) > max_chars or end_line < total_lines or start_line > 1
        return {
            "content": joined[:max_chars],
            "truncated": truncated,
            "start_line": start_line,
            "end_line": min(end_line, total_lines) if total_lines else 0,
            "total_lines": total_lines,
            "line_count": len(joined[:max_chars].splitlines()),
        }
    sliced = text[:max_chars]
    return {
        "content": sliced,
        "truncated": len(text) > max_chars,
        "total_lines": total_lines,
        "line_count": len(sliced.splitlines()),
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
    start_line_raw = args.get("start_line")
    end_line_raw = args.get("end_line")
    try:
        preview = sandbox_service.preview(
            context.workspace_id,
            SandboxPreviewRequest(workspace_id=context.workspace_id, path=relative),
        )
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    if start_line_raw is not None or end_line_raw is not None:
        root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
        target = (root / relative).resolve()
        try:
            full_text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            full_text = str(getattr(preview, "content", "") or "")
        payload = _sandbox_preview_payload(preview, max_chars=max_chars)
        payload.update(
            _slice_text_by_lines(
                full_text,
                start_line_raw=start_line_raw,
                end_line_raw=end_line_raw,
                max_chars=max_chars,
            )
        )
    else:
        payload = _sandbox_preview_payload(preview, max_chars=max_chars)
        content_str = str(payload.get("content") or "")
        payload["line_count"] = len(content_str.splitlines())
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
                explicitDestructivePolicy=True,
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
        indexed = cast(Any, indexed).model_copy(update={"sandbox_path": absolute, "sandbox_dirty": False})
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
            indexed = cast(Any, indexed).model_copy(update={"sandbox_path": absolute, "sandbox_dirty": False})
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
