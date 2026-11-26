"""Phase 2: 8 dual-domain orthogonal tool primitives for Trainer 2.0 (Pi-agent paradigm).

Converges the 43 legacy coach tools into 8 clean, composable primitives split
strictly across two authority domains plus learning state:

- ``<ProjectRoot>`` (STRICTLY READ-ONLY — learner's codebase):
  1. ``project_read``   — inspect current file, list/read project files, modules, symbols, diff impact
  2. ``project_verify`` — diagnostics, practice verification, rubric review, anchor comparison

- ``<LibraryRoot>`` (FULL PI AUTONOMY + ``.trash/`` soft-delete + auto FTS5 indexing):
  3. ``library_read``   — search FTS5 library, read excerpts, list/read/grep sandbox files & folders
  4. ``library_write``  — write, surgical edit, mkdir, rename/move, ``.trash/`` soft_delete, restore,
                          import URL/workspace file, organize, curate, save lecture note, refresh index
                          (every content mutation auto-indexes into SQLite FTS5!)
  5. ``library_exec``   — bounded shell/script execution strictly inside ``cwd=<LibraryRoot>``
                          (blocks irreversible deletes & ``<ProjectRoot>`` escapes; auto-indexes outputs)
  6. ``web_fetch``      — web search, page fetch, academic papers, learning materials, evidence check

- Learning State Domain:
  7. ``learning_inspect`` — inspect plan, learning truth, recall memory, list skills
  8. ``learning_action``  — host-gated formal plan commit, learning note, task mint, skill invoke, image gen
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from ..core.models import (
    SandboxDeleteRequest,
    SandboxMkdirRequest,
    SandboxRenameRequest,
    SandboxRestoreRequest,
    SandboxWriteRequest,
)
from .tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    _enum,
    _explicit_learning_note_request_allowed,
    _formal_plan_mutation_allowed,
    _handle_analyze_project_impact,
    _handle_assess_research_evidence,
    _handle_compare_with_anchor,
    _handle_curate_library_resources,
    _handle_delete_resource,
    _handle_fetch_web_page,
    _handle_generate_image,
    _handle_import_resource_url,
    _handle_import_workspace_file,
    _handle_index_sandbox_file,
    _handle_inspect_current_file,
    _handle_inspect_learning_truth,
    _handle_inspect_plan,
    _handle_invoke_skill,
    _handle_list_library_folders,
    _handle_list_project_modules,
    _handle_list_resources,
    _handle_list_sandbox,
    _handle_list_skills,
    _handle_list_workspace_files,
    _handle_next_task,
    _handle_organize_resources,
    _handle_read_project_symbol,
    _handle_read_resource_excerpt,
    _handle_read_sandbox_file,
    _handle_read_workspace_file,
    _handle_recall_memory,
    _handle_record_learning_note,
    _handle_refresh_resource_index,
    _handle_restore_resource,
    _handle_run_diagnostics,
    _handle_run_rubric_review,
    _handle_save_formal_plan,
    _handle_save_lecture_note,
    _handle_search_academic_papers,
    _handle_search_learning_materials,
    _handle_search_resources,
    _handle_specify_task,
    _handle_verify_practice_current_file,
    _handle_web_search,
    _handle_write_sandbox_file,
    _match_resource_by_sandbox_path,
    _reindex_matching_sandbox_resource,
    _safe_sandbox_relative_path,
    _sandbox_service,
    _string,
    _task_mint_tool_allowed,
)

logger = logging.getLogger("trainer.llm.tool_primitives")

ORTHOGONAL_PRIMITIVE_NAMES: tuple[str, ...] = (
    "project_read",
    "project_verify",
    "library_read",
    "library_write",
    "library_exec",
    "web_fetch",
    "learning_inspect",
    "learning_action",
)

ORTHOGONAL_PRIMITIVE_SET: frozenset[str] = frozenset(ORTHOGONAL_PRIMITIVE_NAMES)

_INDEXABLE_LIBRARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".html",
        ".htm",
        ".tex",
        ".pdf",
        ".epub",
        ".docx",
    }
)

# Guardrails for library_exec: forbid irreversible deletes, privilege escalation,
# pipe-to-shell, and path traversal outside <LibraryRoot>.
_LIBRARY_EXEC_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?:^|[;&|]\s*)rm\s+", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of rm so deletions stay recoverable in .trash/.",
    ),
    (
        re.compile(r"\bunlink\s+", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of unlink.",
    ),
    (
        re.compile(r"\brmdir\s+", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of rmdir.",
    ),
    (
        re.compile(r"\bsudo\b|\bsu\b|\bchmod\b|\bchown\b|\bmkfs\b|\bdd\s+if=", re.IGNORECASE),
        "Privileged or destructive system commands are forbidden in library_exec.",
    ),
    (
        re.compile(r"\|\s*(?:ba|z|da)?sh\b", re.IGNORECASE),
        "Piping remote or generated content directly into a shell is forbidden.",
    ),
    (
        re.compile(r"\bgit\s+push\b", re.IGNORECASE),
        "Remote git push is forbidden in library_exec.",
    ),
    (
        re.compile(r"(?:^|[\s'\"=/])(?:\.\./|\.\.\\)"),
        "Parent directory traversal ('..') is forbidden; library_exec is strictly confined to <LibraryRoot>.",
    ),
)

_MAX_EXEC_TIMEOUT_SECONDS = 30.0
_DEFAULT_EXEC_TIMEOUT_SECONDS = 15.0
_MAX_EXEC_OUTPUT_BYTES = 16_384


# ---------------------------------------------------------------------------
# Auto-indexing helpers for <LibraryRoot>
# ---------------------------------------------------------------------------


async def _auto_index_library_path(
    context: ToolContext,
    relative_path: str,
    *,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Ensure a file inside <LibraryRoot> is indexed in SQLite FTS5 right after mutation."""
    sandbox_service = _sandbox_service(context)
    resource_service = (
        getattr(context.runtime, "resource_service", None) if context.runtime is not None else None
    )
    if sandbox_service is None or resource_service is None:
        return {"auto_indexed": False, "reason": "service_unavailable"}
    try:
        root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
        candidate = (root / relative_path).resolve()
        if not candidate.exists() or not candidate.is_file():
            return {"auto_indexed": False, "reason": "not_a_file"}
        if candidate.suffix.lower() not in _INDEXABLE_LIBRARY_EXTENSIONS:
            return {"auto_indexed": False, "reason": "extension_skipped"}
        existing = _match_resource_by_sandbox_path(
            context.runtime, context.workspace_id, relative_path
        )
        if existing is not None:
            reindexed = _reindex_matching_sandbox_resource(context, relative_path)
            return {
                "auto_indexed": True,
                "mode": "reindexed",
                "resource_id": getattr(existing, "id", None),
                "library": reindexed,
            }
        indexed = await _handle_index_sandbox_file(
            context,
            {
                "path": relative_path,
                "name": Path(relative_path).name,
                **({"tags": tags} if tags else {}),
            },
        )
        return {
            "auto_indexed": bool(indexed.get("ok")),
            "mode": "indexed_new",
            "resource_id": indexed.get("resource_id"),
            "library": indexed,
        }
    except Exception as exc:  # noqa: BLE001 - best-effort auto-indexing never fails the write
        logger.warning("library_auto_index_failed path=%s err=%s", relative_path, exc)
        return {"auto_indexed": False, "reason": exc.__class__.__name__, "detail": str(exc)}


def _is_within_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _workspace_project_root(context: ToolContext) -> Path | None:
    runtime = context.runtime
    resolver = getattr(runtime, "resolve_workspace_path", None) if runtime is not None else None
    if not callable(resolver):
        return None
    raw = resolver(context.workspace_id)
    if not raw:
        return None
    try:
        return Path(str(raw)).resolve()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. project_read (<ProjectRoot> strictly read-only)
# ---------------------------------------------------------------------------


async def _handle_project_read(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "read").strip().lower()
    if action == "inspect_current":
        result = await _handle_inspect_current_file(context, args)
    elif action == "list":
        mapped = dict(args)
        if not mapped.get("directory") and mapped.get("path"):
            mapped["directory"] = mapped["path"]
        if not mapped.get("pattern") and mapped.get("query"):
            mapped["pattern"] = mapped["query"]
        result = await _handle_list_workspace_files(context, mapped)
    elif action == "read":
        result = await _handle_read_workspace_file(context, args)
    elif action == "modules":
        result = await _handle_list_project_modules(context, args)
    elif action == "symbol":
        mapped = dict(args)
        if not mapped.get("name") and mapped.get("symbol"):
            mapped["name"] = mapped["symbol"]
        if not mapped.get("file") and mapped.get("path"):
            mapped["file"] = mapped["path"]
        result = await _handle_read_project_symbol(context, mapped)
    elif action == "impact":
        result = await _handle_analyze_project_impact(context, args)
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported project_read action {action!r}. "
                "Use one of: inspect_current, list, read, modules, symbol, impact."
            ),
        }
    if isinstance(result, dict):
        result.setdefault("domain", "project_readonly")
        result.setdefault("action", action)
    return result


# ---------------------------------------------------------------------------
# 2. project_verify (<ProjectRoot> strictly read-only verification)
# ---------------------------------------------------------------------------


async def _handle_project_verify(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "diagnostics").strip().lower()
    extra = context.extra if isinstance(context.extra, dict) else {}
    if action == "diagnostics":
        mapped = dict(args)
        if not mapped.get("path"):
            current_file = extra.get("current_file")
            if isinstance(current_file, dict) and current_file.get("path"):
                mapped["path"] = current_file["path"]
        result = await _handle_run_diagnostics(context, mapped)
    elif action == "verify_practice":
        if extra.get("completed_training_return_feedback") is True:
            return {
                "ok": False,
                "error": "tool_not_available",
                "detail": (
                    "Practice verification is already recorded for this completed training return."
                ),
            }
        result = await _handle_verify_practice_current_file(context, args)
    elif action == "rubric_review":
        if extra.get("rubric_review_allowed") is not True:
            return {
                "ok": False,
                "error": "rubric_review_not_allowed",
                "detail": "rubric_review is only available in a host-gated practice turn with a card rubric attached.",
            }
        result = await _handle_run_rubric_review(context, args)
    elif action == "compare_anchor":
        result = await _handle_compare_with_anchor(context, args)
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported project_verify action {action!r}. "
                "Use one of: diagnostics, verify_practice, rubric_review, compare_anchor."
            ),
        }
    if isinstance(result, dict):
        result.setdefault("domain", "project_readonly")
        result.setdefault("action", action)
    return result


# ---------------------------------------------------------------------------
# 3. library_read (<LibraryRoot> search, read, list, grep)
# ---------------------------------------------------------------------------


def _grep_library_root(
    root: Path,
    pattern: str,
    *,
    subdir: str | None = None,
    limit: int = 40,
    include_trash: bool = False,
) -> dict[str, Any]:
    base = root
    if subdir:
        safe_sub = _safe_sandbox_relative_path(subdir, field_name="path")
        base = (root / safe_sub).resolve()
        if not _is_within_root(root, base):
            return {
                "ok": False,
                "error": "invalid_path",
                "detail": "Search path escapes <LibraryRoot>.",
            }
        if not base.exists():
            return {
                "ok": False,
                "error": "not_found",
                "detail": f"Path not found in library: {safe_sub}",
            }
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
    matches: list[dict[str, Any]] = []
    scanned_files = 0
    for dirpath, dirnames, filenames in os.walk(base):
        if not include_trash:
            dirnames[:] = [
                d
                for d in dirnames
                if d not in {".trash", "trash", ".trainer-trash"} and not d.startswith(".git")
            ]
        for filename in sorted(filenames):
            file_path = Path(dirpath) / filename
            if file_path.suffix.lower() not in _INDEXABLE_LIBRARY_EXTENSIONS:
                continue
            try:
                if file_path.stat().st_size > 1_048_576:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned_files += 1
            rel = file_path.resolve().relative_to(root.resolve()).as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append({"path": rel, "line": line_no, "text": line.strip()[:240]})
                    if len(matches) >= limit:
                        return {
                            "ok": True,
                            "domain": "library_sandbox",
                            "action": "grep",
                            "pattern": pattern,
                            "scanned_files": scanned_files,
                            "truncated": True,
                            "matches": matches,
                        }
    return {
        "ok": True,
        "domain": "library_sandbox",
        "action": "grep",
        "pattern": pattern,
        "scanned_files": scanned_files,
        "truncated": False,
        "matches": matches,
    }


async def _handle_library_read(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "search").strip().lower()
    if action == "search":
        result = await _handle_search_resources(context, args)
        raw_ids = args.get("resource_ids")
        if isinstance(raw_ids, list) and raw_ids and isinstance(result, dict):
            allowed_ids = {str(rid).strip() for rid in raw_ids if str(rid).strip()}
            hits = result.get("hits")
            if allowed_ids and isinstance(hits, list):
                result = dict(result)
                result["hits"] = [
                    h
                    for h in hits
                    if isinstance(h, dict)
                    and str(h.get("resource_id") or h.get("id") or "").strip() in allowed_ids
                ]
    elif action == "excerpt":
        mapped = dict(args)
        if mapped.get("chars") is None and mapped.get("max_chars") is not None:
            mapped["chars"] = mapped["max_chars"]
        result = await _handle_read_resource_excerpt(context, mapped)
    elif action == "list_resources":
        result = await _handle_list_resources(context, args)
    elif action == "list_folders":
        result = await _handle_list_library_folders(context, args)
    elif action == "list_files":
        result = await _handle_list_sandbox(context, args)
    elif action == "read_file":
        result = await _handle_read_sandbox_file(context, args)
    elif action == "grep":
        sandbox_service = _sandbox_service(context)
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        pattern = str(args.get("query") or args.get("pattern") or "").strip()
        if not pattern:
            return {
                "ok": False,
                "error": "missing_pattern",
                "detail": "library_read(action='grep') requires query or pattern.",
            }
        root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
        try:
            limit = max(1, min(int(args.get("limit", 40)), 100))
        except Exception:
            limit = 40
        result = _grep_library_root(
            root,
            pattern,
            subdir=str(args.get("path") or "").strip() or None,
            limit=limit,
            include_trash=args.get("include_trash") is True,
        )
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported library_read action {action!r}. "
                "Use one of: search, excerpt, list_resources, list_folders, list_files, read_file, grep."
            ),
        }
    if isinstance(result, dict):
        result.setdefault("domain", "library_sandbox")
        result["action"] = action
    return result


# ---------------------------------------------------------------------------
# 4. library_write (<LibraryRoot> full Pi writes + .trash/ soft-delete + auto FTS5)
# ---------------------------------------------------------------------------


def _infer_curate_sub_action(args: dict[str, Any]) -> str:
    explicit = str(args.get("curate_action") or args.get("operation") or "").strip().lower()
    if explicit:
        return explicit
    folder_path = str(args.get("folder_path") or "").strip()
    new_folder_path = str(args.get("new_folder_path") or "").strip()
    resource_id = str(args.get("resource_id") or "").strip()
    title = str(args.get("title") or "").strip()
    if folder_path and new_folder_path:
        return "rename_folder"
    if resource_id and folder_path:
        return "move_to_folder"
    if folder_path and not resource_id:
        return "create_folder"
    if resource_id and title:
        return "rename_resource"
    if resource_id and isinstance(args.get("tags"), list):
        return "tag_resource"
    return ""


_LIBRARY_WRITE_INTENT_HINTS: tuple[str, ...] = (
    "资料库",
    "讲稿",
    "备课",
    "笔记",
    "沙箱",
    "整理",
    "归档",
    "导入",
    "保存",
    "写入",
    "新建",
    "创建",
    "重命名",
    "移动",
    "删除",
    "移入回收站",
    "恢复",
    "刷新索引",
    ".trash",
    "library",
    "sandbox",
    "resource",
    "resources",
    "save",
    "write",
    "edit",
    "mkdir",
    "rename",
    "move",
    "delete",
    "trash",
    "restore",
    "import",
    "organize",
    "curate",
    "reindex",
)


def _library_mutation_allowed_in_agent_turn(context: ToolContext, action: str) -> bool:
    extra = context.extra if isinstance(context.extra, dict) else {}
    # Direct unit/API invocations without agent-loop turn flags stay unrestricted.
    if "allow_coach_only_tools" not in extra:
        return True
    if (
        extra.get("library_sandbox_work") is True
        or str(extra.get("active_view") or "").strip().lower() == "resources"
        or bool(extra.get("resource_composer_intent"))
        or extra.get("explicit_resource_organize") is True
        or extra.get("explicit_resource_import") is True
        or extra.get("explicit_lecture_note_save_request") is True
        or extra.get("explicit_learning_note_request") is True
    ):
        return True
    if action == "save_lecture_note":
        # Let _handle_save_lecture_note return its canonical error code.
        return True
    lowered = " ".join(str(extra.get("learner_message") or "").split()).lower()
    return any(hint in lowered for hint in _LIBRARY_WRITE_INTENT_HINTS)


async def _handle_library_write(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "write").strip().lower()
    if not _library_mutation_allowed_in_agent_turn(context, action):
        return {
            "ok": False,
            "domain": "library_sandbox",
            "action": action,
            "error": "library_write_not_requested",
            "detail": (
                "Library mutations require working in Resources or an explicit learner "
                "request to save, import, edit, or organize library materials."
            ),
        }
    sandbox_service = _sandbox_service(context)

    if action == "write":
        result = await _handle_write_sandbox_file(context, args)
        if isinstance(result, dict) and result.get("ok") and result.get("path"):
            index_info = await _auto_index_library_path(
                context,
                str(result["path"]),
                tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
            )
            result["auto_indexed"] = index_info.get("auto_indexed", False)
            if index_info.get("resource_id"):
                result["resource_id"] = index_info["resource_id"]
        return _stamp_library_result(result, action)

    if action == "edit":
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        try:
            relative = _safe_sandbox_relative_path(args.get("path"), field_name="path")
        except ValueError as exc:
            return {"ok": False, "error": "invalid_path", "detail": str(exc)}
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        if not isinstance(old_text, str) or not old_text:
            return {
                "ok": False,
                "error": "missing_old_text",
                "detail": "library_write(action='edit') requires non-empty old_text.",
            }
        if not isinstance(new_text, str):
            return {
                "ok": False,
                "error": "missing_new_text",
                "detail": "library_write(action='edit') requires string new_text.",
            }
        root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
        target = (root / relative).resolve()
        if not _is_within_root(root, target):
            return {
                "ok": False,
                "error": "invalid_path",
                "detail": "Edit path escapes <LibraryRoot>.",
            }
        if not target.exists() or not target.is_file():
            return {
                "ok": False,
                "error": "not_found",
                "detail": f"File not found in library: {relative}",
            }
        current_content = target.read_text(encoding="utf-8", errors="replace")
        occurrences = current_content.count(old_text)
        if occurrences == 0:
            return {
                "ok": False,
                "error": "old_text_not_found",
                "detail": f"old_text was not found in {relative}.",
            }
        replace_all = args.get("replace_all") is True
        if occurrences > 1 and not replace_all:
            return {
                "ok": False,
                "error": "ambiguous_edit",
                "detail": f"old_text matched {occurrences} times in {relative}; provide more context or set replace_all=true.",
            }
        updated_content = (
            current_content.replace(old_text, new_text)
            if replace_all
            else current_content.replace(old_text, new_text, 1)
        )
        try:
            sandbox_service.write(
                context.workspace_id,
                SandboxWriteRequest(
                    workspace_id=context.workspace_id,
                    path=relative,
                    content=updated_content,
                    create=False,
                    explicitDestructivePolicy=True,
                ),
            )
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        index_info = await _auto_index_library_path(context, relative)
        return {
            "ok": True,
            "domain": "library_sandbox",
            "action": "edit",
            "path": relative,
            "replacements": occurrences if replace_all else 1,
            "bytes": len(updated_content.encode("utf-8", errors="replace")),
            "auto_indexed": index_info.get("auto_indexed", False),
            **({"resource_id": index_info["resource_id"]} if index_info.get("resource_id") else {}),
        }

    if action == "mkdir":
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        try:
            relative = _safe_sandbox_relative_path(
                args.get("path") or args.get("folder_path"), field_name="path"
            )
        except ValueError as exc:
            return {"ok": False, "error": "invalid_path", "detail": str(exc)}
        try:
            sandbox_service.mkdir(
                context.workspace_id,
                SandboxMkdirRequest(workspace_id=context.workspace_id, path=relative),
            )
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        return {
            "ok": True,
            "domain": "library_sandbox",
            "action": "mkdir",
            "path": relative,
            "created": True,
        }

    if action in {"rename", "move"}:
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        try:
            src_rel = _safe_sandbox_relative_path(args.get("path"), field_name="path")
            dst_rel = _safe_sandbox_relative_path(
                args.get("new_path") or args.get("destination"), field_name="new_path"
            )
        except ValueError as exc:
            return {"ok": False, "error": "invalid_path", "detail": str(exc)}
        try:
            sandbox_service.rename(
                context.workspace_id,
                SandboxRenameRequest(
                    path=src_rel,
                    new_path=dst_rel,
                ),
            )
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        index_info = await _auto_index_library_path(context, dst_rel)
        return {
            "ok": True,
            "domain": "library_sandbox",
            "action": action,
            "path": src_rel,
            "new_path": dst_rel,
            "auto_indexed": index_info.get("auto_indexed", False),
            **({"resource_id": index_info["resource_id"]} if index_info.get("resource_id") else {}),
        }

    if action == "soft_delete":
        if args.get("resource_id"):
            return _stamp_library_result(await _handle_delete_resource(context, args), action)
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        try:
            relative = _safe_sandbox_relative_path(args.get("path"), field_name="path")
        except ValueError as exc:
            return {"ok": False, "error": "invalid_path", "detail": str(exc)}
        try:
            sandbox_service.delete(
                context.workspace_id,
                SandboxDeleteRequest(
                    workspace_id=context.workspace_id,
                    path=relative,
                    explicitDestructivePolicy=True,
                ),
            )
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
        trashed_rel = None
        for trash_name in (".trash", "trash", ".trainer-trash"):
            trash_dir = root / trash_name
            if trash_dir.exists():
                matches = sorted(
                    trash_dir.rglob(Path(relative).name),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if matches:
                    trashed_rel = matches[0].resolve().relative_to(root).as_posix()
                    break
        return {
            "ok": True,
            "domain": "library_sandbox",
            "action": "soft_delete",
            "path": relative,
            "soft_deleted": True,
            "trashed_path": trashed_rel,
        }

    if action == "restore":
        if args.get("resource_id"):
            return _stamp_library_result(await _handle_restore_resource(context, args), action)
        if sandbox_service is None:
            return {
                "ok": False,
                "error": "service_unavailable",
                "detail": "The managed library sandbox is not configured.",
            }
        raw_path = str(args.get("path") or args.get("trashed_path") or "").strip()
        if not raw_path:
            return {
                "ok": False,
                "error": "missing_path",
                "detail": "library_write(action='restore') requires path or resource_id.",
            }
        restore_path = str(args.get("restore_path") or "").strip() or None
        try:
            sandbox_service.restore(
                context.workspace_id,
                SandboxRestoreRequest(
                    workspace_id=context.workspace_id,
                    path=raw_path,
                    restore_path=restore_path,
                    explicitDestructivePolicy=True,
                ),
            )
        except Exception as exc:
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        index_target = restore_path or raw_path
        index_info = await _auto_index_library_path(context, index_target)
        return {
            "ok": True,
            "domain": "library_sandbox",
            "action": "restore",
            "path": raw_path,
            "restored_path": restore_path,
            "auto_indexed": index_info.get("auto_indexed", False),
        }

    if action == "import_url":
        mapped = dict(args)
        if not mapped.get("name") and mapped.get("title"):
            mapped["name"] = mapped["title"]
        return _stamp_library_result(await _handle_import_resource_url(context, mapped), action)
    if action == "import_workspace":
        return _stamp_library_result(await _handle_import_workspace_file(context, args), action)
    if action == "organize":
        return _stamp_library_result(await _handle_organize_resources(context, args), action)
    if action == "curate":
        curate_sub_action = _infer_curate_sub_action(args)
        mapped = dict(args)
        mapped["action"] = curate_sub_action
        curate_result = await _handle_curate_library_resources(context, mapped)
        if isinstance(curate_result, dict):
            curate_result = dict(curate_result)
            if curate_sub_action:
                curate_result["curate_action"] = curate_sub_action
            curate_result["action"] = "curate"
            curate_result.setdefault("domain", "library_sandbox")
        return curate_result
    if action == "save_lecture_note":
        mapped = dict(args)
        if not mapped.get("markdown_content") and mapped.get("content"):
            mapped["markdown_content"] = mapped["content"]
        if not mapped.get("folder") and mapped.get("folder_path"):
            mapped["folder"] = mapped["folder_path"]
        return _stamp_library_result(await _handle_save_lecture_note(context, mapped), action)
    if action == "refresh_index":
        if args.get("path") and not args.get("resource_id"):
            return _stamp_library_result(await _handle_index_sandbox_file(context, args), action)
        return _stamp_library_result(await _handle_refresh_resource_index(context, args), action)

    return {
        "ok": False,
        "error": "invalid_action",
        "detail": (
            f"Unsupported library_write action {action!r}. Use one of: write, edit, mkdir, "
            "rename, move, soft_delete, restore, import_url, import_workspace, organize, curate, "
            "save_lecture_note, refresh_index."
        ),
    }


def _stamp_library_result(result: dict[str, Any], action: str) -> dict[str, Any]:
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("domain", "library_sandbox")
        result["action"] = action
    return result


# ---------------------------------------------------------------------------
# 5. library_exec (<LibraryRoot> bounded shell/script execution)
# ---------------------------------------------------------------------------


def _validate_library_exec_command(
    command: str,
    *,
    library_root: Path,
    project_root: Path | None,
) -> str | None:
    cleaned = command.strip()
    if not cleaned:
        return "library_exec requires a non-empty command."
    for pattern, reason in _LIBRARY_EXEC_FORBIDDEN_PATTERNS:
        if pattern.search(cleaned):
            return reason
    if project_root is not None:
        project_str = str(project_root)
        if project_str and project_str != str(library_root) and project_str in cleaned:
            return "library_exec cannot access <ProjectRoot>; use project_read for read-only codebase inspection."
    for token in re.findall(r"(?:^|\s)(/[^\s'\"|;&]+)", cleaned):
        if token.startswith(("/usr/", "/bin/", "/opt/homebrew/", "/dev/null")):
            continue
        try:
            candidate = Path(token).resolve()
        except Exception:
            continue
        if not _is_within_root(library_root, candidate):
            return f"Absolute path {token!r} escapes <LibraryRoot>."
    return None


async def _handle_library_exec(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if not _library_mutation_allowed_in_agent_turn(context, "exec"):
        return {
            "ok": False,
            "domain": "library_sandbox",
            "error": "library_write_not_requested",
            "detail": (
                "library_exec requires working in Resources or an explicit learner "
                "request to process or organize library files."
            ),
        }
    sandbox_service = _sandbox_service(context)
    if sandbox_service is None:
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "The managed library sandbox is not configured.",
        }
    command = str(args.get("command") or "").strip()
    library_root = Path(sandbox_service.ensure_operation_root(context.workspace_id)).resolve()
    project_root = _workspace_project_root(context)
    rejection = _validate_library_exec_command(
        command,
        library_root=library_root,
        project_root=project_root,
    )
    if rejection is not None:
        return {
            "ok": False,
            "domain": "library_sandbox",
            "error": "command_blocked",
            "detail": rejection,
        }
    try:
        timeout = max(
            1.0,
            min(
                float(args.get("timeout_seconds", _DEFAULT_EXEC_TIMEOUT_SECONDS)),
                _MAX_EXEC_TIMEOUT_SECONDS,
            ),
        )
    except Exception:
        timeout = _DEFAULT_EXEC_TIMEOUT_SECONDS

    started_at = time.time()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(library_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        raw_stdout, raw_stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "ok": False,
            "domain": "library_sandbox",
            "error": "timeout",
            "detail": f"library_exec timed out after {timeout:.1f}s.",
        }

    stdout_text = raw_stdout[:_MAX_EXEC_OUTPUT_BYTES].decode("utf-8", errors="replace")
    stderr_text = raw_stderr[:_MAX_EXEC_OUTPUT_BYTES].decode("utf-8", errors="replace")
    auto_indexed_paths: list[str] = []
    if proc.returncode == 0 and args.get("auto_index") is not False:
        for dirpath, dirnames, filenames in os.walk(library_root):
            dirnames[:] = [d for d in dirnames if d != ".trash" and not d.startswith(".")]
            for filename in filenames:
                file_path = Path(dirpath) / filename
                if file_path.suffix.lower() not in _INDEXABLE_LIBRARY_EXTENSIONS:
                    continue
                try:
                    if file_path.stat().st_mtime >= started_at - 0.5:
                        rel = file_path.resolve().relative_to(library_root).as_posix()
                        info = await _auto_index_library_path(context, rel)
                        if info.get("auto_indexed"):
                            auto_indexed_paths.append(rel)
                except OSError:
                    continue
                if len(auto_indexed_paths) >= 12:
                    break

    return {
        "ok": proc.returncode == 0,
        "domain": "library_sandbox",
        "exit_code": int(proc.returncode or 0),
        "cwd": str(library_root),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "truncated": len(raw_stdout) > _MAX_EXEC_OUTPUT_BYTES
        or len(raw_stderr) > _MAX_EXEC_OUTPUT_BYTES,
        "auto_indexed_paths": auto_indexed_paths,
    }


# ---------------------------------------------------------------------------
# 6. web_fetch (web search, page fetch, papers, learning materials, evidence)
# ---------------------------------------------------------------------------


async def _handle_web_fetch(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or ("fetch" if args.get("url") else "search")).strip().lower()
    extra = context.extra if isinstance(context.extra, dict) else {}
    if extra.get("formal_plan_mutation") is True:
        if extra.get("_formal_research_synthesizing") is True:
            return {
                "ok": False,
                "error": "research_already_concluded",
                "detail": (
                    "Formal plan research has concluded; stop searching and call "
                    "learning_action(action='save_formal_plan', ...) to commit the plan."
                ),
            }
        research_state = extra.get("_learning_material_research_state")
        if (
            isinstance(research_state, dict)
            and research_state.get("status") == "awaiting_model_assessment"
            and action != "assess_evidence"
        ):
            return {
                "ok": False,
                "error": "assessment_required_before_next_search",
                "detail": (
                    "Call web_fetch(action='assess_evidence', ...) to evaluate the fetched "
                    "sources before starting another search."
                ),
            }

    if action == "search":
        result = await _handle_web_search(context, args)
    elif action == "fetch":
        result = await _handle_fetch_web_page(context, args)
    elif action == "papers":
        result = await _handle_search_academic_papers(context, args)
    elif action == "learning_materials":
        result = await _handle_search_learning_materials(context, args)
    elif action == "assess_evidence":
        result = await _handle_assess_research_evidence(context, args)
    elif action == "import_url":
        if not _library_mutation_allowed_in_agent_turn(context, "import_url"):
            return {
                "ok": False,
                "domain": "web_research",
                "action": "import_url",
                "error": "library_write_not_requested",
                "detail": (
                    "Importing a URL into <LibraryRoot> requires working in Resources "
                    "or an explicit learner request to import/save the resource."
                ),
            }
        mapped = dict(args)
        if not mapped.get("name") and mapped.get("title"):
            mapped["name"] = mapped["title"]
        result = await _handle_import_resource_url(context, mapped)
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported web_fetch action {action!r}. "
                "Use one of: search, fetch, papers, learning_materials, assess_evidence, import_url."
            ),
        }
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("domain", "web_research")
        result["action"] = action
    return result


# ---------------------------------------------------------------------------
# 7. learning_inspect (plan, truth, memory, skills)
# ---------------------------------------------------------------------------


async def _handle_learning_inspect(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "plan").strip().lower()
    if action == "plan":
        result = await _handle_inspect_plan(context, args)
    elif action == "truth":
        result = await _handle_inspect_learning_truth(context, args)
    elif action == "memory":
        mapped = dict(args)
        if not mapped.get("focus") and mapped.get("query"):
            mapped["focus"] = mapped["query"]
        if not mapped.get("query") and mapped.get("focus"):
            mapped["query"] = mapped["focus"]
        result = await _handle_recall_memory(context, mapped)
    elif action == "skills":
        result = await _handle_list_skills(context, args)
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported learning_inspect action {action!r}. "
                "Use one of: plan, truth, memory, skills."
            ),
        }
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("domain", "learning_state")
        result["action"] = action
    return result


# ---------------------------------------------------------------------------
# 8. learning_action (host-gated mutations: formal plan, note, task, skill, image)
# ---------------------------------------------------------------------------


async def _handle_learning_action(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if action == "save_formal_plan":
        if not _formal_plan_mutation_allowed(context):
            return {
                "ok": False,
                "error": "formal_plan_mutation_required",
                "detail": "save_formal_plan is only available during an explicit formal plan turn.",
            }
        result = await _handle_save_formal_plan(context, args)
    elif action == "record_note":
        if not _explicit_learning_note_request_allowed(context):
            return {
                "ok": False,
                "error": "explicit_learning_note_request_required",
                "detail": "record_note is only available when the learner explicitly asked to save a note.",
            }
        mapped = dict(args)
        if not mapped.get("note"):
            mapped["note"] = str(mapped.get("content") or mapped.get("observation") or "").strip()
        result = await _handle_record_learning_note(context, mapped)
    elif action == "specify_task":
        if not _task_mint_tool_allowed(context):
            return {
                "ok": False,
                "error": "live_formal_plan_required",
                "detail": "specify_task requires a live-bound formal plan.",
            }
        mapped = dict(args)
        if not mapped.get("natural_language_goal"):
            mapped["natural_language_goal"] = str(
                mapped.get("goal") or mapped.get("prompt") or mapped.get("message") or ""
            ).strip()
        result = await _handle_specify_task(context, mapped)
    elif action == "next_task":
        if not _task_mint_tool_allowed(context):
            return {
                "ok": False,
                "error": "live_formal_plan_required",
                "detail": "next_task requires a live-bound formal plan.",
            }
        mapped = dict(args)
        if not mapped.get("focus_area") and (mapped.get("focus") or mapped.get("goal")):
            mapped["focus_area"] = mapped.get("focus") or mapped.get("goal")
        result = await _handle_next_task(context, mapped)
    elif action == "invoke_skill":
        mapped = dict(args)
        if not mapped.get("skill_id") and mapped.get("skill_name"):
            mapped["skill_id"] = mapped["skill_name"]
        if not mapped.get("task_note") and mapped.get("prompt"):
            mapped["task_note"] = mapped["prompt"]
        result = await _handle_invoke_skill(context, mapped)
    elif action == "generate_image":
        result = await _handle_generate_image(context, args)
    else:
        return {
            "ok": False,
            "error": "invalid_action",
            "detail": (
                f"Unsupported learning_action action {action!r}. "
                "Use one of: save_formal_plan, record_note, specify_task, next_task, invoke_skill, generate_image."
            ),
        }
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        result = dict(result)
        result.setdefault("domain", "learning_state")
        result["action"] = action
    return result


# ---------------------------------------------------------------------------
# Tool definitions & dynamic per-turn mounting
# ---------------------------------------------------------------------------


def build_orthogonal_primitive_tools() -> list[ToolDefinition]:
    """Return the 8 dual-domain orthogonal ToolDefinition primitives."""
    return [
        ToolDefinition(
            name="project_read",
            description=(
                "Read-only inspection of the learner's project codebase (<ProjectRoot>). "
                "Never modifies project code. Use action='inspect_current' for the active editor file, "
                "'list' to browse project files, 'read' to read a source file, 'modules' for repo overview, "
                "'symbol' to locate a function/class, or 'impact' for git diff caller impact."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Read-only project inspection action.",
                        ["inspect_current", "list", "read", "modules", "symbol", "impact"],
                    ),
                    "path": _string(
                        "Relative file or directory path inside <ProjectRoot> (for read/list)."
                    ),
                    "directory": _string(
                        "Optional directory path inside <ProjectRoot> (for action='list')."
                    ),
                    "pattern": _string("Optional glob pattern (for action='list')."),
                    "name": _string("Symbol name to locate (for action='symbol')."),
                    "symbol": _string("Alias for symbol name (for action='symbol')."),
                    "file": _string("Optional path substring filter (for action='symbol')."),
                    "query": _string("Optional filename or substring filter (for action='list')."),
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based start line (for read).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based end line (for read).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional character cap (for read).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Optional item cap (for list/modules).",
                    },
                    "since": _string("Optional git ref for impact diff."),
                    "depth": {"type": "integer", "description": "Caller depth 1-3 for impact."},
                    "resource_id": _string("Optional imported-project resource id."),
                },
                "required": ["action"],
            },
            handler=_handle_project_read,
        ),
        ToolDefinition(
            name="project_verify",
            description=(
                "Read-only verification of the learner's work in <ProjectRoot>: run editor/project "
                "diagnostics, verify practice code against checks, run host-gated rubric review, "
                "or compare an imitation submission with an anchor passage."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Verification action.",
                        ["diagnostics", "verify_practice", "rubric_review", "compare_anchor"],
                    ),
                    "path": _string(
                        "Optional relative file path for diagnostics/practice verification."
                    ),
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Observable acceptance criteria (for verify_practice).",
                    },
                    "expected_symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Expected function/class/variable names (for verify_practice).",
                    },
                    "submission": _string(
                        "Learner text submission (for compare_anchor / rubric_review)."
                    ),
                    "anchor_text": _string("Optional inline anchor passage (for compare_anchor)."),
                    "resource_id": _string("Optional library resource id (for compare_anchor)."),
                    "anchor_id": _string("Optional paragraph anchor id (for compare_anchor)."),
                },
                "required": ["action"],
            },
            handler=_handle_project_verify,
        ),
        ToolDefinition(
            name="library_read",
            description=(
                "Read and search the learner's managed resource library (<LibraryRoot>): "
                "FTS5 full-text search ('search'), anchored excerpts ('excerpt'), list resources/folders/files, "
                "read a library file ('read_file'), or regex grep across library files ('grep')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Library read/search action.",
                        [
                            "search",
                            "excerpt",
                            "list_resources",
                            "list_folders",
                            "list_files",
                            "read_file",
                            "grep",
                        ],
                    ),
                    "query": _string("Search query or grep pattern."),
                    "pattern": _string("Regex or literal pattern (for action='grep')."),
                    "path": _string(
                        "Relative path inside <LibraryRoot> (for read_file, list_files, or scoped grep)."
                    ),
                    "resource_id": _string("Resource id (for excerpt)."),
                    "resource_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional resource ID filter list (for search).",
                    },
                    "anchor_id": _string("Optional ¶ anchor id (for excerpt)."),
                    "version_id": _string("Optional pinned resource version id (for excerpt)."),
                    "content_hash": _string("Optional pinned content hash (for excerpt)."),
                    "mode": _enum("Optional search mode.", ["broad", "narrow", "verify"]),
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based start line (for read_file).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based end line (for read_file).",
                    },
                    "limit": {"type": "integer", "description": "Maximum results to return."},
                    "max_chars": {"type": "integer", "description": "Maximum characters to read."},
                    "chars": {"type": "integer", "description": "Alias for max_chars (for excerpt)."},
                    "include_trash": {
                        "type": "boolean",
                        "description": "Include .trash/ entries when listing or grepping (default false).",
                    },
                },
                "required": ["action"],
            },
            handler=_handle_library_read,
        ),
        ToolDefinition(
            name="library_write",
            description=(
                "Full autonomous file & resource management inside <LibraryRoot> (never touches <ProjectRoot>). "
                "Supports write, surgical edit (old_text -> new_text), mkdir, rename/move, safe .trash/ soft_delete, "
                "restore, import_url, import_workspace, organize, curate, save_lecture_note, and refresh_index. "
                "Every content write/edit/rename/restore automatically updates the SQLite FTS5 index."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Library mutation action.",
                        [
                            "write",
                            "edit",
                            "mkdir",
                            "rename",
                            "move",
                            "soft_delete",
                            "restore",
                            "import_url",
                            "import_workspace",
                            "organize",
                            "curate",
                            "save_lecture_note",
                            "refresh_index",
                        ],
                    ),
                    "path": _string(
                        "Relative path inside <LibraryRoot> (or workspace file path for import_workspace)."
                    ),
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Batch workspace paths (for action='import_workspace').",
                    },
                    "directory": _string(
                        "Workspace directory to import (for action='import_workspace')."
                    ),
                    "new_path": _string(
                        "Destination relative path inside <LibraryRoot> (for rename/move)."
                    ),
                    "restore_path": _string(
                        "Optional destination path when restoring from .trash/."
                    ),
                    "content": _string("Full text content (for write / save_lecture_note)."),
                    "markdown_content": _string(
                        "Markdown lecture content (alias of content for save_lecture_note)."
                    ),
                    "folder": _string(
                        "Target library folder name (for save_lecture_note / import_url / import_workspace)."
                    ),
                    "old_text": _string("Exact text to replace (for action='edit')."),
                    "new_text": _string("Replacement text (for action='edit')."),
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences in edit (default false).",
                    },
                    "url": _string("Web URL to import (for import_url)."),
                    "resource_id": _string(
                        "Resource id (for soft_delete / restore / refresh_index / curate)."
                    ),
                    "title": _string(
                        "Optional title (for save_lecture_note / import_url / curate)."
                    ),
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags.",
                    },
                    "curate_action": _enum(
                        "Sub-operation when action='curate'.",
                        [
                            "create_folder",
                            "rename_folder",
                            "move_to_folder",
                            "rename_resource",
                            "tag_resource",
                        ],
                    ),
                    "folder_path": _string("Library folder path (for curate)."),
                    "new_folder_path": _string("New library folder path (for curate rename_folder)."),
                    "operations": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Sandbox organization operations list (for action='organize').",
                    },
                    "undo_id": _string("Optional organization undo history ID (for action='organize')."),
                },
                "required": ["action"],
            },
            handler=_handle_library_write,
        ),
        ToolDefinition(
            name="library_exec",
            description=(
                "Run a bounded shell/script command (e.g. python3, rg, wc, pandoc, awk) strictly inside "
                "cwd=<LibraryRoot> to batch-process notes, parse PDFs/CSV, or organize library data. "
                "Irreversible delete commands (rm/unlink) and paths escaping <LibraryRoot> are blocked; "
                "newly created/updated text files are automatically indexed into FTS5."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": _string("Shell command to execute inside <LibraryRoot>."),
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Execution timeout in seconds (1-30, default 15).",
                    },
                    "auto_index": {
                        "type": "boolean",
                        "description": "Automatically FTS5-index newly modified files in <LibraryRoot> (default true).",
                    },
                },
                "required": ["command"],
            },
            handler=_handle_library_exec,
        ),
        ToolDefinition(
            name="web_fetch",
            description=(
                "Retrieve external web and academic evidence: search the web ('search'), fetch a specific URL ('fetch'), "
                "search academic papers ('papers'), find curated learning materials ('learning_materials'), "
                "assess research evidence ('assess_evidence'), or import a URL into <LibraryRoot> ('import_url')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Web/research action.",
                        [
                            "search",
                            "fetch",
                            "papers",
                            "learning_materials",
                            "assess_evidence",
                            "import_url",
                        ],
                    ),
                    "query": _string("Search query (for search / papers / learning_materials)."),
                    "url": _string("Target URL (for fetch / import_url)."),
                    "limit": {"type": "integer", "description": "Maximum search results."},
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional character cap (for fetch).",
                    },
                    "include_github": {
                        "type": "boolean",
                        "description": "Include GitHub repositories alongside arXiv papers (for action='papers').",
                    },
                    "focus_area": _string("Optional focus area label (for learning_materials)."),
                    "required_facets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-8 distinct facets the research must substantiate (for learning_materials).",
                    },
                    "preferred_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional authoritative domains to prioritize (for learning_materials).",
                    },
                    "verdict": _enum(
                        "Structured sufficiency verdict (for assess_evidence).",
                        ["sufficient", "gaps_remain", "exhausted_with_gaps"],
                    ),
                    "evidence_standard": {
                        "type": "object",
                        "properties": {
                            "risk_level": _enum(
                                "Task risk level.",
                                ["exploratory", "normal", "high_stakes"],
                            ),
                            "minimum_independent_sources": {
                                "type": "integer",
                                "description": "Minimum independent sources required (1-8).",
                            },
                            "requires_authoritative_source": {
                                "type": "boolean",
                                "description": "Whether primary/official documentation is required.",
                            },
                            "claim_types": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "freshness_requirement": _enum(
                                "Evidence freshness requirement.",
                                ["historical", "stable", "current", "latest"],
                            ),
                            "applicability_scope": _string(
                                "Concrete scope (>=16 chars) this evidence applies to."
                            ),
                            "stopping_rule": _string(
                                "Explicit stopping rule (>=20 chars) for concluding search."
                            ),
                            "unresolved_uncertainties": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "quality_checks": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": (
                                    "Checks for coverage, source_quality, recency, contradictions, applicability."
                                ),
                            },
                        },
                        "description": (
                            "Task-adapted evidence standard (risk_level, minimum_independent_sources, "
                            "requires_authoritative_source, claim_types, freshness_requirement, "
                            "applicability_scope, stopping_rule, unresolved_uncertainties, quality_checks) "
                            "for action='assess_evidence'."
                        ),
                    },
                    "facet_assessments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "facet": _string("Required facet name."),
                                "status": _enum(
                                    "Facet coverage status.",
                                    ["covered", "partial", "missing"],
                                ),
                                "source_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "evidence_quotes": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                },
                                "rationale": _string("Concrete rationale (>=16 chars)."),
                            },
                        },
                        "description": (
                            "Per-facet judgments ({facet, status, source_ids, evidence_quotes, rationale}) "
                            "for action='assess_evidence'."
                        ),
                    },
                    "title": _string("Optional resource title (for import_url)."),
                    "name": _string("Alias for resource title (for import_url)."),
                    "folder": _string("Optional target folder (for import_url)."),
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags (for import_url).",
                    },
                },
                "required": ["action"],
            },
            handler=_handle_web_fetch,
        ),
        ToolDefinition(
            name="learning_inspect",
            description=(
                "Inspect the learner's current learning state: active learning plan ('plan'), "
                "verified mastery/progress truth ('truth'), recalled memory ('memory'), or available skills ('skills')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum("Inspection target.", ["plan", "truth", "memory", "skills"]),
                    "query": _string("Optional query for memory recall or truth lookup."),
                    "focus": _string("Optional focus topic for memory recall."),
                    "section": _enum(
                        "Optional truth section filter (for action='truth').",
                        ["all", "plan", "goal", "evidence", "progress", "mastery", "review", "practice"],
                    ),
                    "evidence_limit": {
                        "type": "integer",
                        "description": "Maximum evidence records to return (for action='truth').",
                    },
                    "kind": _enum(
                        "Optional skill kind filter (for action='skills').",
                        ["tutor", "knowledge", "action", "custom"],
                    ),
                },
                "required": ["action"],
            },
            handler=_handle_learning_inspect,
        ),
        ToolDefinition(
            name="learning_action",
            description=(
                "Perform governed learning-state actions: commit a formal learning plan ('save_formal_plan'), "
                "save an explicit learning note ('record_note'), mint/advance a plan task ('specify_task'/'next_task'), "
                "invoke a skill ('invoke_skill'), or generate an instructional diagram ('generate_image')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Governed learning action.",
                        [
                            "save_formal_plan",
                            "record_note",
                            "specify_task",
                            "next_task",
                            "invoke_skill",
                            "generate_image",
                        ],
                    ),
                    "title": _string("Plan or diagram title (for save_formal_plan / generate_image)."),
                    "summary": _string("Plan summary/objective (for save_formal_plan)."),
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": _string("Optional stage identifier."),
                                "title": _string("Stage title."),
                                "goal": _string("Concrete stage goal."),
                                "outcomes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "resources": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "status": _enum(
                                    "Stage status.", ["pending", "active", "completed"]
                                ),
                            },
                            "required": ["title", "goal"],
                        },
                        "description": "Ordered formal plan stages (for save_formal_plan).",
                    },
                    "cadence": _string("Optional study/review cadence (for save_formal_plan)."),
                    "current_step": _string(
                        "Concrete current step to execute first (for save_formal_plan)."
                    ),
                    "why_now": _string("Why this plan/step matters now (for save_formal_plan)."),
                    "verify_method": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Verification criteria (for save_formal_plan).",
                    },
                    "blocked_reason": _string("Optional blocker note (for save_formal_plan)."),
                    "next_after_current": _string(
                        "Next step after current_step completes (for save_formal_plan)."
                    ),
                    "note": _string("Observation text to record (for record_note)."),
                    "content": _string("Alias for observation text (for record_note)."),
                    "kind": _string("Optional note kind (for record_note, default 'observation')."),
                    "natural_language_goal": _string(
                        "Concrete task objective (for specify_task)."
                    ),
                    "goal": _string("Alias for task objective (for specify_task)."),
                    "focus_area": _string("Optional focus area (for next_task)."),
                    "skill_id": _string("Skill id, $trigger, or name (for invoke_skill)."),
                    "skill_name": _string("Alias for skill_id (for invoke_skill)."),
                    "task_note": _string("Optional task context passed to skill (for invoke_skill)."),
                    "prompt": _string(
                        "Visual description prompt (for generate_image) or task instruction."
                    ),
                    "style": _string("Optional visual style (for generate_image, default 'diagram')."),
                    "aspect_ratio": _string(
                        "Optional aspect ratio (for generate_image, default '16:9')."
                    ),
                    "save_to_library": {
                        "type": "boolean",
                        "description": "Persist generated image in <LibraryRoot> (default true).",
                    },
                },
                "required": ["action"],
            },
            handler=_handle_learning_action,
        ),
    ]


def register_orthogonal_primitives(registry: ToolRegistry) -> None:
    """Register all 8 dual-domain orthogonal primitives on a ToolRegistry."""
    for tool in build_orthogonal_primitive_tools():
        if registry.get(tool.name) is None:
            registry.register(tool)


_WEB_RESEARCH_HINTS = (
    "联网",
    "上网",
    "搜索",
    "搜一下",
    "查一下",
    "论文",
    "arxiv",
    "最新进展",
    "前沿进展",
    "研究进展",
    "http://",
    "https://",
    "web search",
    "search online",
    "latest research",
)

_LIBRARY_HINTS = (
    "资料库",
    "讲稿",
    "备课",
    "笔记",
    "沙箱",
    "library",
    "sandbox",
    "resource",
    "resources",
    "整理",
    "归档",
    "导入",
    "回收站",
    ".trash",
)

_PROJECT_HINTS = (
    "这个项目",
    "当前项目",
    "工作区",
    "代码库",
    "仓库",
    "源码",
    "文件结构",
    "项目结构",
    "项目架构",
    "代码架构",
    "报错",
    "诊断",
    "测试",
    "this project",
    "this repo",
    "workspace",
    "codebase",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
)


def select_orthogonal_tools_for_turn(
    extra: dict[str, Any],
    learner_message: str | None = None,
) -> list[str]:
    """Dynamically mount only the orthogonal primitives needed for this turn (4-8 tools)."""
    active_view = str(extra.get("active_view") or "").strip().lower()
    lowered = " ".join(str(learner_message or "").split()).lower()

    is_library_turn = (
        active_view == "resources"
        or extra.get("library_sandbox_work") is True
        or extra.get("explicit_lecture_note_save_request") is True
        or extra.get("explicit_resource_import") is True
        or extra.get("explicit_resource_organize") is True
        or bool(extra.get("resource_composer_intent"))
        or any(hint in lowered for hint in _LIBRARY_HINTS)
    )
    is_web_turn = any(hint in lowered for hint in _WEB_RESEARCH_HINTS)
    is_project_turn = (
        active_view == "training"
        or extra.get("rubric_review_allowed") is True
        or bool(extra.get("exercise_prompt"))
        or bool(extra.get("current_file"))
        or bool(extra.get("workspace_file_snapshot"))
        or any(hint in lowered for hint in _PROJECT_HINTS)
    )
    is_plan_turn = active_view == "plan" or extra.get("formal_plan_mutation") is True

    selected: list[str] = []

    def _add(*names: str) -> None:
        for name in names:
            if name not in selected:
                selected.append(name)

    if is_library_turn:
        _add("library_read", "library_write", "library_exec", "web_fetch", "learning_inspect")
    if is_web_turn:
        _add("web_fetch", "library_read", "library_write", "learning_inspect")
    if is_project_turn:
        _add("project_read", "project_verify", "library_read", "learning_inspect")
    if is_plan_turn:
        _add("learning_inspect", "learning_action", "library_read", "project_read", "web_fetch")

    # Add learning_action when explicit learning-state writes or skills/images are requested.
    if (
        extra.get("explicit_learning_note_request") is True
        or extra.get("live_formal_plan_for_task_mint") is True
        or any(k in lowered for k in ("画图", "配图", "示意图", "diagram", "skill", "技能"))
    ):
        _add("learning_action")

    if not selected:
        # Fallback for generic tool-lane turns: mount the 8 orthogonal primitives (never 43).
        return list(ORTHOGONAL_PRIMITIVE_NAMES)
    return selected


__all__ = [
    "ORTHOGONAL_PRIMITIVE_NAMES",
    "ORTHOGONAL_PRIMITIVE_SET",
    "build_orthogonal_primitive_tools",
    "register_orthogonal_primitives",
    "select_orthogonal_tools_for_turn",
]
