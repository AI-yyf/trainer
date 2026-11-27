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
import contextlib
import inspect
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
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
# symlinks, tilde/env home escapes, pipe-to-shell, and path traversal outside <LibraryRoot>.
_LIBRARY_EXEC_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?:^|[;&|\n`$(]\s*|(?:xargs|env|command)\s+)(?:['\"]?/(?:bin|usr/bin)/)?['\"]?rm['\"]?(?:\s|$)",
            re.IGNORECASE,
        ),
        "Use library_write(action='soft_delete') instead of rm so deletions stay recoverable in .trash/.",
    ),
    (
        re.compile(r"\bunlink\b\s*(?:\(|[^\s])", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of unlink.",
    ),
    (
        re.compile(r"\brmdir\b\s*(?:\(|[^\s])", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of rmdir.",
    ),
    (
        re.compile(r"\bfind\b[^\n;|&]*\s-(?:delete|exec\s+(?:['\"]?/(?:bin|usr/bin)/)?['\"]?rm\b)", re.IGNORECASE),
        "Use library_write(action='soft_delete') instead of find -delete / -exec rm.",
    ),
    (
        re.compile(
            r"\b(?:os\.(?:remove|unlink|rmdir|removedirs)|shutil\.rmtree|Path\([^)]*\)\.unlink|fs\.(?:rmSync|unlinkSync|rmdirSync|rm\b))\s*\(",
            re.IGNORECASE,
        ),
        "Direct file deletion in inline scripts is forbidden; use library_write(action='soft_delete') so deletions stay recoverable in .trash/.",
    ),
    (
        re.compile(r"\b(?:git\s+clean\b|shred\b)", re.IGNORECASE),
        "Irreversible cleanup commands (git clean / shred) are forbidden in library_exec.",
    ),
    (
        re.compile(r"(?:^|[;&|\n`$(]\s*)ln\s+|\bos\.symlink\s*\(", re.IGNORECASE),
        "Creating symlinks is forbidden in library_exec to prevent sandbox path escapes.",
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
        re.compile(r"(?:^|[\s'\"=:(])~(?:/|\s|$|['\"])"),
        "Home-directory (~) expansion is forbidden; use relative paths inside <LibraryRoot>.",
    ),
    (
        re.compile(r"\$(?:\{)?(?:HOME|USERPROFILE|OLDPWD|TMPDIR)(?:\})?\b", re.IGNORECASE),
        "Environment-variable directory escapes ($HOME / $OLDPWD / $TMPDIR) are forbidden in library_exec.",
    ),
    (
        re.compile(r"(?:^|[;&|\n]\s*)cd(?:\s*|\s+-)(?:$|[;&|\n])"),
        "Bare 'cd' / 'cd -' escapes <LibraryRoot>; stay inside relative paths under <LibraryRoot>.",
    ),
    (
        re.compile(r"(?:^|[\s'\"=/(\[])\.\.(?:[/\\]|$|[\s'\"])" ),
        "Parent directory traversal ('..') is forbidden; library_exec is strictly confined to <LibraryRoot>.",
    ),
    (
        re.compile(
            r"\bxargs\b|\beval\b|\bbase64\s+(?:-[dD]|--decode)\b|\b(?:chr|b64decode|fromhex)\s*\(",
            re.IGNORECASE,
        ),
        "Dynamic command/path decoding (xargs / eval / base64 -d / chr / b64decode) is forbidden in library_exec.",
    ),
    (
        re.compile(
            r"\bpython[0-9.]*\s+-[A-Za-z]*[SIE]|\b(?:node|perl|ruby)\s+-e\b|\bosascript\b",
            re.IGNORECASE,
        ),
        "Bypassing Python site sandbox flags (-S/-I/-E) or unsandboxed inline interpreters is forbidden in library_exec.",
    ),
    (
        re.compile(
            r"(?:^|[;&|\n`$(]\s*|(?:env|command)\s+)(?:['\"]?/(?:bin|usr/bin|usr/local/bin|opt/homebrew/bin)/)?['\"]?(?:curl|wget|nc|ncat|netcat|ssh|scp|sftp|rsync|ftp|telnet)['\"]?(?:\s|$)",
            re.IGNORECASE,
        ),
        "Outbound network commands are forbidden in library_exec; use web_fetch instead.",
    ),
)

_SENSITIVE_HOST_HOME_SUBPATHS: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
    ".azure",
    ".config/gcloud",
    ".config/gh",
    "Library/Keychains",
    "Library/Cookies",
    "Library/Accounts",
    "Library/Mail",
    "Library/Messages",
    "Library/Safari",
)

_SENSITIVE_HOST_HOME_LITERALS: tuple[str, ...] = (
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".gitconfig",
    ".git-credentials",
    ".env",
    ".bash_history",
    ".zsh_history",
    ".python_history",
)

_ALLOWED_SYSTEM_EXEC_PREFIXES: tuple[str, ...] = (
    "/usr/bin/",
    "/usr/local/bin/",
    "/usr/sbin/",
    "/bin/",
    "/sbin/",
    "/opt/homebrew/bin/",
    "/opt/homebrew/opt/",
    "/opt/homebrew/Cellar/",
    "/Library/Developer/CommandLineTools/usr/bin/",
)

_STRIPPED_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONEXECUTABLE",
        "__PYVENV_LAUNCHER__",
        "PYINSTALLER_RESET_ENVIRONMENT",
        "_MEIPASS",
        "_MEIPASS2",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_FRAMEWORK_PATH",
    }
)

_ALLOWED_SUBPROCESS_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TZ",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
    }
)

_MAX_EXEC_TIMEOUT_SECONDS = 30.0
_DEFAULT_EXEC_TIMEOUT_SECONDS = 15.0
_MAX_EXEC_OUTPUT_BYTES = 30_000
_MAX_RAW_CAPTURE_BYTES = 262_144

_MACOS_SANDBOX_USABLE: bool | None = None
_LINUX_BWRAP_BIN: str | None | bool = False

_PYTHON_AUDIT_SITECUSTOMIZE = '''"""Trainer C-level PEP 578 sys.addaudithook sandbox guard for library_exec."""
import os
import sys
from pathlib import Path

_LIB_ROOT = Path(os.environ.get("TRAINER_LIBRARY_ROOT", os.getcwd())).resolve()
_RAW_PROJ = os.environ.get("TRAINER_PROJECT_ROOT", "").strip()
_PROJ_ROOT = Path(_RAW_PROJ).resolve() if _RAW_PROJ else None
_SYS_READ_ROOTS = tuple(
    Path(p).resolve()
    for p in (
        "/usr",
        "/bin",
        "/sbin",
        "/opt",
        "/Library",
        "/System",
        "/private/etc",
        "/etc",
        "/dev",
        "/var/select",
        "/private/var/select",
        sys.prefix,
        sys.base_prefix,
        sys.exec_prefix,
    )
    if os.path.exists(p)
)
_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_RDWR
    | getattr(os, "O_CREAT", 0)
    | getattr(os, "O_TRUNC", 0)
    | getattr(os, "O_APPEND", 0)
)

def _under(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False

def _resolve_arg(raw) -> Path | None:
    if isinstance(raw, int) or raw is None:
        return None
    try:
        p = Path(os.fsdecode(raw))
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        return p.resolve()
    except Exception:
        return None

def _check_read(target: Path, event: str) -> None:
    if str(target).startswith("/dev/"):
        return
    if _under(_LIB_ROOT, target):
        return
    if _PROJ_ROOT is not None and _PROJ_ROOT != _LIB_ROOT and _under(_PROJ_ROOT, target):
        raise PermissionError(f"Sandbox blocked {event} on <ProjectRoot>: {target}")
    if any(_under(r, target) for r in _SYS_READ_ROOTS):
        return
    raise PermissionError(f"Sandbox blocked {event} outside <LibraryRoot>: {target}")

def _check_write(target: Path, event: str) -> None:
    if str(target) == "/dev/null":
        return
    if _PROJ_ROOT is not None and _PROJ_ROOT != _LIB_ROOT and _under(_PROJ_ROOT, target):
        raise PermissionError(f"Sandbox blocked write to read-only <ProjectRoot>: {target}")
    if not _under(_LIB_ROOT, target):
        raise PermissionError(f"Sandbox blocked write outside <LibraryRoot>: {target}")

def _audit(event: str, args: tuple) -> None:
    if event == "open":
        raw_path, mode, flags = (args + (None, None, 0))[:3]
        target = _resolve_arg(raw_path)
        if target is None:
            return
        is_write = bool(isinstance(flags, int) and (flags & _WRITE_FLAGS)) or (
            isinstance(mode, str) and any(m in mode for m in ("w", "a", "x", "+"))
        )
        if is_write:
            _check_write(target, event)
        else:
            _check_read(target, event)
    elif event in ("os.chdir", "os.listdir", "os.scandir", "glob.glob", "glob.glob/2"):
        target = _resolve_arg(args[0] if args else None)
        if target is not None and not _under(_LIB_ROOT, target):
            raise PermissionError(f"Sandbox blocked {event} outside <LibraryRoot>: {target}")
    elif event in (
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "shutil.rmtree",
        "os.symlink",
        "os.link",
        "os.chmod",
        "os.chown",
    ):
        raise PermissionError(f"Sandbox blocked destructive {event}; use library_write(action='soft_delete').")
    elif event in ("os.rename", "os.replace"):
        src = _resolve_arg(args[0] if len(args) > 0 else None)
        dst = _resolve_arg(args[1] if len(args) > 1 else None)
        if (src and not _under(_LIB_ROOT, src)) or (dst and not _under(_LIB_ROOT, dst)):
            raise PermissionError(f"Sandbox blocked {event} outside <LibraryRoot>.")
    elif event in ("os.mkdir", "os.makedirs"):
        target = _resolve_arg(args[0] if args else None)
        if target is not None:
            _check_write(target, event)
    elif event in (
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "urllib.Request",
        "http.client.connect",
        "ftplib.connect",
        "smtplib.connect",
    ):
        raise PermissionError(f"Network access ({event}) is blocked inside library_exec; use web_fetch instead.")
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"):
        raise PermissionError(f"Nested process spawning ({event}) is blocked inside library_exec Python scripts.")
    elif event in ("ctypes.dlopen", "ctypes.dlsym"):
        raise PermissionError(f"Direct native library loading ({event}) is blocked inside library_exec.")
    elif event == "sqlite3.connect":
        raw_db = args[0] if args else None
        if isinstance(raw_db, str) and raw_db.strip() in {":memory:", ""}:
            return
        target = _resolve_arg(raw_db)
        if target is None or not _under(_LIB_ROOT, target):
            raise PermissionError(f"Sandbox blocked sqlite3.connect outside <LibraryRoot>: {raw_db}")

sys.addaudithook(_audit)
'''


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


def _extract_candidate_absolute_paths(cleaned: str) -> tuple[list[str], str | None]:
    try:
        lexed_tokens = shlex.split(cleaned, posix=True)
    except ValueError:
        return [], "Malformed shell quoting in library_exec command."

    candidates: list[str] = []

    def _add(raw_token: str) -> None:
        token = raw_token.strip().strip("'\"")
        if token.startswith("/") and len(token) > 1 and token not in candidates:
            candidates.append(token)

    for token in lexed_tokens:
        _add(token)
        if "=" in token:
            _, rhs = token.split("=", 1)
            _add(rhs)
        for embedded in re.findall(
            r"(?:^|[\s'\"=(,\[])(/(?!/)[A-Za-z0-9._+@~-]+(?:/[A-Za-z0-9._+@~ -]*)*)",
            token,
        ):
            _add(embedded)

    for quoted in re.findall(r"['\"](/(?!/)[^'\"\n;|&<>()]+)['\"]", cleaned):
        _add(quoted)
    for unquoted in re.findall(r"(?:^|[\s=(,\[])(/(?!/)[^\s'\"|;&<>()]+)", cleaned):
        _add(unquoted)
    return candidates, None


def _ensure_python_audit_guard_dir(library_root: Path) -> Path:
    tmp_dir = library_root / ".trainer-tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    uid_tag = str(os.getuid()) if hasattr(os, "getuid") else "user"
    guard_dir = Path(tempfile.gettempdir()).resolve() / f"trainer-exec-guard-{uid_tag}"
    guard_dir.mkdir(parents=True, exist_ok=True)
    site_file = guard_dir / "sitecustomize.py"
    needs_write = (
        not site_file.exists()
        or site_file.read_text(encoding="utf-8", errors="ignore") != _PYTHON_AUDIT_SITECUSTOMIZE
    )
    if needs_write:
        with contextlib.suppress(OSError):
            os.chmod(guard_dir, 0o700)
        if site_file.exists():
            with contextlib.suppress(OSError):
                os.chmod(site_file, 0o600)
        site_file.write_text(_PYTHON_AUDIT_SITECUSTOMIZE, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(site_file, 0o444)
        os.chmod(guard_dir, 0o555)
    return guard_dir


def _macos_sandbox_exec_usable() -> bool:
    global _MACOS_SANDBOX_USABLE
    if _MACOS_SANDBOX_USABLE is not None:
        return _MACOS_SANDBOX_USABLE
    if sys.platform != "darwin":
        _MACOS_SANDBOX_USABLE = False
        return False
    sb = shutil.which("sandbox-exec")
    if not sb:
        _MACOS_SANDBOX_USABLE = False
        return False
    try:
        probe = subprocess.run(
            [sb, "-p", "(version 1)(allow default)", "/usr/bin/true"],
            capture_output=True,
            timeout=2.0,
        )
        _MACOS_SANDBOX_USABLE = probe.returncode == 0
    except Exception:
        _MACOS_SANDBOX_USABLE = False
    return _MACOS_SANDBOX_USABLE


def _linux_bwrap_bin() -> str | None:
    global _LINUX_BWRAP_BIN
    if _LINUX_BWRAP_BIN is not False:
        return _LINUX_BWRAP_BIN if isinstance(_LINUX_BWRAP_BIN, str) else None
    if not sys.platform.startswith("linux"):
        _LINUX_BWRAP_BIN = None
        return None
    bwrap = shutil.which("bwrap")
    if not bwrap:
        _LINUX_BWRAP_BIN = None
        return None
    try:
        probe = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "/bin/true"],
            capture_output=True,
            timeout=2.0,
        )
        _LINUX_BWRAP_BIN = bwrap if probe.returncode == 0 else None
    except Exception:
        _LINUX_BWRAP_BIN = None
    return _LINUX_BWRAP_BIN


def _lexical_norm_path(raw: str | Path) -> Path:
    return Path(os.path.normpath(os.path.abspath(str(raw))))


def _sbpl_escape_str(raw_path: str | Path) -> str:
    return str(raw_path).replace("\\", "\\\\").replace('"', '\\"')


def _sbpl_escape(path: Path) -> str:
    return _sbpl_escape_str(path.resolve())


def _resolve_real_host_homes() -> list[Path]:
    """Return deduplicated lexical host home directories without stat()ing restricted paths."""
    raw_candidates: list[str] = []
    if hasattr(os, "getuid"):
        with contextlib.suppress(Exception):
            import pwd

            pw_dir = pwd.getpwuid(os.getuid()).pw_dir
            if pw_dir:
                raw_candidates.append(pw_dir)
    for env_key in ("HOME", "USERPROFILE"):
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            raw_candidates.append(env_val)

    homes: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not raw or not os.path.isabs(raw):
            continue
        normed = _lexical_norm_path(raw)
        for variant in (
            normed,
            *(
                [_lexical_norm_path(f"/private{normed}")]
                if str(normed).startswith("/var/")
                else []
            ),
        ):
            key = str(variant)
            if key not in seen:
                seen.add(key)
                homes.append(variant)
    return homes


def _is_within_lexical(root: Path, candidate: Path) -> bool:
    try:
        _lexical_norm_path(candidate).relative_to(_lexical_norm_path(root))
        return True
    except ValueError:
        return False


def _build_macos_seatbelt_profile(library_root: Path, project_root: Path | None) -> str:
    resolved_lib = library_root.resolve()
    lib_escaped = _sbpl_escape(resolved_lib)
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny appleevent-send)",
        "(deny file-write*)",
        f'(allow file-write* (subpath "{lib_escaped}") (literal "/dev/null") (literal "/dev/dtracehelper"))',
    ]
    emitted_rules: set[str] = set()

    def _emit_rule(rule: str) -> None:
        if rule not in emitted_rules:
            emitted_rules.add(rule)
            lines.append(rule)

    # Default-deny reads across real host home directories, then explicitly re-allow
    # <LibraryRoot> and the active Python runtime prefix (if located under host home).
    for host_home in _resolve_real_host_homes():
        if _lexical_norm_path(host_home) == _lexical_norm_path(resolved_lib):
            continue
        _emit_rule(f'(deny file-read* (subpath "{_sbpl_escape_str(host_home)}"))')
        for rel_sub in _SENSITIVE_HOST_HOME_SUBPATHS:
            cand_sub = _lexical_norm_path(host_home / rel_sub)
            if _is_within_lexical(cand_sub, resolved_lib) or _is_within_lexical(
                resolved_lib, cand_sub
            ):
                continue
            _emit_rule(f'(deny file-read* (subpath "{_sbpl_escape_str(cand_sub)}"))')
        for rel_lit in _SENSITIVE_HOST_HOME_LITERALS:
            cand_lit = _lexical_norm_path(host_home / rel_lit)
            if cand_lit == _lexical_norm_path(resolved_lib) or _is_within_lexical(
                resolved_lib, cand_lit
            ):
                continue
            _emit_rule(f'(deny file-read* (literal "{_sbpl_escape_str(cand_lit)}"))')

    _emit_rule(f'(allow file-read* (subpath "{lib_escaped}"))')
    for runtime_root_raw in {sys.prefix, sys.base_prefix}:
        if not runtime_root_raw:
            continue
        runtime_root = _lexical_norm_path(runtime_root_raw)
        if any(_is_within_lexical(h, runtime_root) for h in _resolve_real_host_homes()):
            _emit_rule(f'(allow file-read* (subpath "{_sbpl_escape_str(runtime_root)}"))')

    # Keep <ProjectRoot> denied LAST so last-rule-wins SBPL always isolates it.
    if project_root is not None and project_root.resolve() != resolved_lib:
        resolved_proj = project_root.resolve()
        if not _is_within_root(resolved_lib, resolved_proj) and not _is_within_root(
            resolved_proj, resolved_lib
        ):
            proj_escaped = _sbpl_escape(resolved_proj)
            _emit_rule(f'(deny file-read* (subpath "{proj_escaped}"))')

    return "\n".join(lines)


def _has_unquoted_shell_operators(command: str) -> bool:
    """Return True if command contains shell control/redirect/expansion operators."""
    in_single = False
    in_double = False
    escaped = False
    length = len(command)
    for idx, ch in enumerate(command):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_single:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if not in_single and ch == "`":
            return True
        if in_double and ch == "$":
            nxt = command[idx + 1] if idx + 1 < length else ""
            if nxt in ("(", "{") or nxt.isalpha() or nxt == "_":
                return True
        if not in_single and not in_double:
            if ch in "|&;<>()\n\r$":
                return True
    return in_single or in_double or escaped


def _build_direct_audited_fallback_argv(command: str) -> tuple[list[str] | None, str]:
    """Build a zero-/bin/sh argv for audited Python -c or literal echo when kernel sandboxes are absent."""
    if _has_unquoted_shell_operators(command):
        return None, "unavailable"
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None, "unavailable"
    if not tokens:
        return None, "unavailable"

    head = tokens[0]
    if head in {"echo", "/bin/echo"}:
        echo_bin = "/bin/echo" if os.path.exists("/bin/echo") else (shutil.which("echo") or "")
        if not echo_bin:
            return None, "unavailable"
        return [echo_bin, *tokens[1:]], "direct_echo_no_shell"

    idx = 0
    if head in {"env", "/usr/bin/env"}:
        if len(tokens) < 4:
            return None, "unavailable"
        idx = 1
        head = tokens[idx]

    py_basenames = {"python", "python3", f"python{sys.version_info.major}.{sys.version_info.minor}"}
    head_name = os.path.basename(head)
    if head_name not in py_basenames:
        return None, "unavailable"
    if os.path.isabs(head) and not head.startswith(_ALLOWED_SYSTEM_EXEC_PREFIXES):
        return None, "unavailable"

    rest = tokens[idx + 1 :]
    allowed_flags: list[str] = []
    while rest and rest[0].startswith("-") and rest[0] != "-c":
        if rest[0] in {"-B", "-u"}:
            allowed_flags.append(rest.pop(0))
        else:
            return None, "unavailable"

    if len(rest) != 2 or rest[0] != "-c" or not rest[1]:
        return None, "unavailable"

    py_bin = (
        sys.executable
        if not getattr(sys, "frozen", False) and sys.executable and os.path.exists(sys.executable)
        else (shutil.which("python3") or shutil.which("python") or "")
    )
    if not py_bin:
        return None, "unavailable"
    return [py_bin, "-B", *allowed_flags, "-c", rest[1]], "python_audit_exec"


def _build_sandboxed_exec_argv(
    command: str,
    *,
    library_root: Path,
    project_root: Path | None,
) -> tuple[list[str] | None, str]:
    """Return (argv, sandbox_backend) preferring OS kernel sandboxes and forbidding raw /bin/sh."""
    resolved_lib = library_root.resolve()
    if _macos_sandbox_exec_usable():
        sb = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
        profile = _build_macos_seatbelt_profile(resolved_lib, project_root)
        return [sb, "-p", profile, "/bin/sh", "-c", command], "macos_seatbelt"
    bwrap = _linux_bwrap_bin()
    if bwrap:
        argv = [
            bwrap,
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--clearenv",
            "--setenv",
            "HOME",
            str(resolved_lib),
            "--setenv",
            "PWD",
            str(resolved_lib),
            "--setenv",
            "TMPDIR",
            str(resolved_lib / ".trainer-tmp"),
            "--setenv",
            "TRAINER_LIBRARY_ROOT",
            str(resolved_lib),
            "--setenv",
            "PYTHONIOENCODING",
            "utf-8",
            "--setenv",
            "PYTHONNOUSERSITE",
            "1",
            "--setenv",
            "LANG",
            "en_US.UTF-8",
            "--setenv",
            "LC_ALL",
            "en_US.UTF-8",
            "--setenv",
            "PATH",
            "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "--die-with-parent",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(resolved_lib),
            str(resolved_lib),
            "--dev",
            "/dev",
            "--proc",
            "/proc",
        ]
        mounted_targets: set[str] = set()
        if project_root is not None and project_root.resolve() != resolved_lib:
            resolved_proj = project_root.resolve()
            if (
                not _is_within_root(resolved_lib, resolved_proj)
                and not _is_within_root(resolved_proj, resolved_lib)
                and resolved_proj.exists()
            ):
                mounted_targets.add(str(resolved_proj))
                argv.extend(["--tmpfs", str(resolved_proj)])
        for host_home in _resolve_real_host_homes():
            if _lexical_norm_path(host_home) == _lexical_norm_path(resolved_lib):
                continue
            # Never stat() real /Users/* paths on macOS; only probe on Linux or inside temp test dirs.
            can_probe = sys.platform.startswith("linux") or str(host_home).startswith(
                ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
            )
            if not can_probe:
                continue
            for rel_sub in _SENSITIVE_HOST_HOME_SUBPATHS:
                cand_sub = _lexical_norm_path(host_home / rel_sub)
                if _is_within_lexical(cand_sub, resolved_lib) or _is_within_lexical(
                    resolved_lib, cand_sub
                ):
                    continue
                is_existing_dir = False
                with contextlib.suppress(OSError):
                    is_existing_dir = cand_sub.is_dir()
                if is_existing_dir and str(cand_sub) not in mounted_targets:
                    mounted_targets.add(str(cand_sub))
                    argv.extend(["--tmpfs", str(cand_sub)])
            for rel_lit in _SENSITIVE_HOST_HOME_LITERALS:
                cand_lit = _lexical_norm_path(host_home / rel_lit)
                if _is_within_lexical(resolved_lib, cand_lit):
                    continue
                is_existing_file = False
                with contextlib.suppress(OSError):
                    is_existing_file = cand_lit.is_file()
                if is_existing_file and str(cand_lit) not in mounted_targets:
                    mounted_targets.add(str(cand_lit))
                    argv.extend(["--ro-bind", "/dev/null", str(cand_lit)])
        argv.extend(["--chdir", str(resolved_lib), "/bin/sh", "-c", command])
        return argv, "linux_bwrap"
    return _build_direct_audited_fallback_argv(command)


def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if proc.pid:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError, AttributeError):
            os.killpg(proc.pid, signal.SIGKILL)
            return
    with contextlib.suppress(ProcessLookupError, OSError):
        proc.kill()


def _build_library_exec_env(
    library_root: Path,
    *,
    project_root: Path | None = None,
    inject_audit_guard: bool = False,
) -> dict[str, str]:
    """Build an isolated subprocess environment safe under packaged PyInstaller sidecars."""
    clean_env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper_key = key.upper()
        if (
            upper_key not in _ALLOWED_SUBPROCESS_ENV_KEYS
            or key in _STRIPPED_SUBPROCESS_ENV_KEYS
            or upper_key in _STRIPPED_SUBPROCESS_ENV_KEYS
            or upper_key.startswith(("_MEI", "PYINSTALLER_"))
        ):
            continue
        clean_env[key] = value

    raw_path_parts = [part.strip() for part in clean_env.get("PATH", "").split(os.pathsep) if part.strip()]
    filtered_parts = [
        part
        for part in raw_path_parts
        if "_MEI" not in part and "PyInstaller" not in part
    ]
    preferred_prefixes = ["/opt/homebrew/bin", "/usr/local/bin"]
    fallback_suffixes = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    merged_path: list[str] = []
    for segment in [*preferred_prefixes, *filtered_parts, *fallback_suffixes]:
        if segment and segment not in merged_path:
            merged_path.append(segment)
    clean_env["PATH"] = os.pathsep.join(merged_path)
    clean_env["HOME"] = str(library_root)
    clean_env["PWD"] = str(library_root)
    clean_env["TMPDIR"] = str(library_root / ".trainer-tmp")
    clean_env["TRAINER_LIBRARY_ROOT"] = str(library_root)
    if project_root is not None:
        clean_env["TRAINER_PROJECT_ROOT"] = str(project_root.resolve())
    if inject_audit_guard:
        guard_dir = _ensure_python_audit_guard_dir(library_root)
        clean_env["PYTHONPATH"] = str(guard_dir)
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONNOUSERSITE"] = "1"
    clean_env.setdefault("LANG", "en_US.UTF-8")
    clean_env.setdefault("LC_ALL", "en_US.UTF-8")
    return clean_env


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
    resolved_library_root = library_root.resolve()
    resolved_project_root = project_root.resolve() if project_root is not None else None
    if resolved_project_root is not None and resolved_project_root != resolved_library_root:
        project_str = str(resolved_project_root)
        raw_project_str = str(project_root)
        lowered_cmd = cleaned.casefold()
        if (
            (project_str and project_str.casefold() in lowered_cmd)
            or (raw_project_str and raw_project_str.casefold() in lowered_cmd)
        ):
            return "library_exec cannot access <ProjectRoot>; use project_read for read-only codebase inspection."
    candidates, lex_error = _extract_candidate_absolute_paths(cleaned)
    if lex_error is not None:
        return lex_error
    for token in candidates:
        if token == "/dev/null":
            continue
        if ".." in Path(token).parts:
            return f"Path traversal in {token!r} escapes <LibraryRoot>."
        if token.startswith(_ALLOWED_SYSTEM_EXEC_PREFIXES):
            continue
        try:
            candidate = Path(token).resolve()
        except Exception:
            return f"Invalid absolute path {token!r} in library_exec."
        if (
            resolved_project_root is not None
            and resolved_project_root != resolved_library_root
            and _is_within_root(resolved_project_root, candidate)
            and not _is_within_root(resolved_library_root, candidate)
        ):
            return "library_exec cannot access <ProjectRoot>; use project_read for read-only codebase inspection."
        if not _is_within_root(resolved_library_root, candidate):
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

    from .harness import invalidate_sandbox_operations, truncate_tool_payload

    started_at = time.time()
    exec_env = _build_library_exec_env(
        library_root,
        project_root=project_root,
        inject_audit_guard=True,
    )
    argv, sandbox_backend = _build_sandboxed_exec_argv(
        command,
        library_root=library_root,
        project_root=project_root,
    )
    if argv is None:
        return {
            "ok": False,
            "domain": "library_sandbox",
            "sandbox_backend": sandbox_backend,
            "error": "sandbox_unavailable",
            "detail": (
                "library_exec requires an OS kernel sandbox (macOS Seatbelt sandbox-exec "
                "or Linux bubblewrap bwrap) and fails closed when neither is available."
            ),
        }
    extra = context.extra if isinstance(context.extra, dict) else {}
    raw_cancel = extra.get("_stream_cancel_event") or extra.get("stream_cancel_event")
    cancel_event = raw_cancel if isinstance(raw_cancel, asyncio.Event) else None
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(library_root),
        env=exec_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    comm_task = asyncio.create_task(proc.communicate())
    cancel_wait_task: asyncio.Task[bool] | None = (
        asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
    )
    try:
        if cancel_wait_task is not None:
            done, _ = await asyncio.wait(
                {comm_task, cancel_wait_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_wait_task in done:
                _terminate_process_group(proc)
                with contextlib.suppress(Exception):
                    await comm_task
                raise asyncio.CancelledError
            if comm_task not in done:
                raise asyncio.TimeoutError
            raw_stdout, raw_stderr = comm_task.result()
        else:
            raw_stdout, raw_stderr = await asyncio.wait_for(comm_task, timeout=timeout)
    except asyncio.TimeoutError:
        _terminate_process_group(proc)
        with contextlib.suppress(Exception):
            await comm_task
        return {
            "ok": False,
            "domain": "library_sandbox",
            "error": "timeout",
            "detail": f"library_exec timed out after {timeout:.1f}s.",
        }
    except BaseException:
        _terminate_process_group(proc)
        with contextlib.suppress(Exception):
            await comm_task
        raise
    finally:
        if cancel_wait_task is not None and not cancel_wait_task.done():
            cancel_wait_task.cancel()

    decoded_stdout = raw_stdout[:_MAX_RAW_CAPTURE_BYTES].decode("utf-8", errors="replace")
    decoded_stderr = raw_stderr[:_MAX_RAW_CAPTURE_BYTES].decode("utf-8", errors="replace")
    stdout_text = truncate_tool_payload(decoded_stdout, limit=_MAX_EXEC_OUTPUT_BYTES)
    stderr_text = truncate_tool_payload(decoded_stderr, limit=_MAX_EXEC_OUTPUT_BYTES)
    was_truncated = (
        len(raw_stdout) > _MAX_RAW_CAPTURE_BYTES
        or len(raw_stderr) > _MAX_RAW_CAPTURE_BYTES
        or len(decoded_stdout) > _MAX_EXEC_OUTPUT_BYTES
        or len(decoded_stderr) > _MAX_EXEC_OUTPUT_BYTES
    )
    if proc.returncode == 0:
        invalidate_sandbox_operations(context.runtime, context.workspace_id)
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
                except (OSError, ValueError):
                    continue
                if len(auto_indexed_paths) >= 12:
                    break

    return {
        "ok": proc.returncode == 0,
        "domain": "library_sandbox",
        "sandbox_backend": sandbox_backend,
        "exit_code": int(proc.returncode or 0),
        "cwd": str(library_root),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "truncated": was_truncated,
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
    """Return the 8 dual-domain orthogonal ToolDefinition primitives (slimmed Pi-style schemas)."""
    return [
        ToolDefinition(
            name="project_read",
            description=(
                "Read-only inspection of <ProjectRoot> (never edits code): "
                "'inspect_current', 'list', 'read', 'modules', 'symbol', or 'impact'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
                        ["inspect_current", "list", "read", "modules", "symbol", "impact"],
                    ),
                    "path": _string("Relative path in <ProjectRoot> (read/list)."),
                    "directory": _string("Directory in <ProjectRoot> (list)."),
                    "pattern": _string("Glob filter (list)."),
                    "name": _string("Symbol name (symbol)."),
                    "symbol": _string("Alias of name (symbol)."),
                    "file": _string("Path filter (symbol)."),
                    "query": _string("Substring filter (list)."),
                    "start_line": {"type": "integer", "description": "1-based start line."},
                    "end_line": {"type": "integer", "description": "1-based end line."},
                    "max_chars": {"type": "integer", "description": "Char cap."},
                    "limit": {"type": "integer", "description": "Item cap."},
                    "since": _string("Git ref (impact)."),
                    "depth": {"type": "integer", "description": "Caller depth 1-3 (impact)."},
                    "resource_id": _string("Imported-project resource id."),
                },
                "required": ["action"],
            },
            handler=_handle_project_read,
        ),
        ToolDefinition(
            name="project_verify",
            description=(
                "Read-only verification in <ProjectRoot>: 'diagnostics', 'verify_practice', "
                "'rubric_review', or 'compare_anchor'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
                        ["diagnostics", "verify_practice", "rubric_review", "compare_anchor"],
                    ),
                    "path": _string("Relative file path."),
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Checks for verify_practice.",
                    },
                    "expected_symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Expected symbols (verify_practice).",
                    },
                    "submission": _string("Learner submission (compare_anchor/rubric_review)."),
                    "anchor_text": _string("Inline anchor text (compare_anchor)."),
                    "resource_id": _string("Library resource id (compare_anchor)."),
                    "anchor_id": _string("Anchor id (compare_anchor)."),
                },
                "required": ["action"],
            },
            handler=_handle_project_verify,
        ),
        ToolDefinition(
            name="library_read",
            description=(
                "Search or read <LibraryRoot>: FTS5 'search', anchored 'excerpt', "
                "'list_resources', 'list_folders', 'list_files', 'read_file', or 'grep'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
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
                    "pattern": _string("Alias for grep pattern."),
                    "path": _string("Relative path in <LibraryRoot>."),
                    "resource_id": _string("Resource id (excerpt)."),
                    "resource_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter resource IDs (search).",
                    },
                    "anchor_id": _string("Paragraph ¶ anchor id (excerpt)."),
                    "version_id": _string("Pinned version id (excerpt)."),
                    "content_hash": _string("Pinned content hash (excerpt)."),
                    "mode": _enum("Search mode.", ["broad", "narrow", "verify"]),
                    "start_line": {"type": "integer", "description": "1-based start line."},
                    "end_line": {"type": "integer", "description": "1-based end line."},
                    "limit": {"type": "integer", "description": "Max items."},
                    "max_chars": {"type": "integer", "description": "Max chars."},
                    "chars": {"type": "integer", "description": "Alias of max_chars."},
                    "include_trash": {"type": "boolean", "description": "Include .trash/."},
                },
                "required": ["action"],
            },
            handler=_handle_library_read,
        ),
        ToolDefinition(
            name="library_write",
            description=(
                "Manage files/resources inside <LibraryRoot> (auto-FTS5 indexed; soft_delete uses .trash/): "
                "write, edit, mkdir, rename, move, soft_delete, restore, import_url, import_workspace, "
                "organize, curate, save_lecture_note, refresh_index."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
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
                    "path": _string("Relative path in <LibraryRoot> (or workspace path for import_workspace)."),
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Batch workspace paths (import_workspace).",
                    },
                    "directory": _string("Workspace directory (import_workspace)."),
                    "new_path": _string("Target path in <LibraryRoot> (rename/move)."),
                    "restore_path": _string("Target path (restore)."),
                    "content": _string("Text content (write/save_lecture_note)."),
                    "markdown_content": _string("Alias of content (save_lecture_note)."),
                    "folder": _string("Target folder."),
                    "old_text": _string("Exact text to replace (edit)."),
                    "new_text": _string("Replacement text (edit)."),
                    "replace_all": {"type": "boolean", "description": "Replace all matches (edit)."},
                    "url": _string("Source URL (import_url)."),
                    "resource_id": _string("Resource id."),
                    "title": _string("Title."),
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "curate_action": _enum(
                        "Sub-action for curate.",
                        [
                            "create_folder",
                            "rename_folder",
                            "move_to_folder",
                            "rename_resource",
                            "tag_resource",
                        ],
                    ),
                    "folder_path": _string("Folder path (curate)."),
                    "new_folder_path": _string("New folder path (curate)."),
                    "operations": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Batch ops (organize).",
                    },
                    "undo_id": _string("Undo history id (organize)."),
                },
                "required": ["action"],
            },
            handler=_handle_library_write,
        ),
        ToolDefinition(
            name="library_exec",
            description=(
                "Run a bounded command strictly inside cwd=<LibraryRoot> (blocks rm/escapes; auto-indexes new files)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": _string("Shell command in <LibraryRoot>."),
                    "timeout_seconds": {"type": "number", "description": "Timeout 1-30s (default 15)."},
                    "auto_index": {"type": "boolean", "description": "Auto-index modified files (default true)."},
                },
                "required": ["command"],
            },
            handler=_handle_library_exec,
        ),
        ToolDefinition(
            name="web_fetch",
            description=(
                "External research: 'search', 'fetch', 'papers', 'learning_materials', "
                "'assess_evidence', or 'import_url' (into <LibraryRoot>)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
                        [
                            "search",
                            "fetch",
                            "papers",
                            "learning_materials",
                            "assess_evidence",
                            "import_url",
                        ],
                    ),
                    "query": _string("Search query."),
                    "url": _string("Target URL (fetch/import_url)."),
                    "limit": {"type": "integer", "description": "Max results."},
                    "max_chars": {"type": "integer", "description": "Char cap (fetch)."},
                    "include_github": {"type": "boolean", "description": "Include GitHub repos (papers)."},
                    "focus_area": _string("Focus label (learning_materials)."),
                    "required_facets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-8 facets (learning_materials).",
                    },
                    "preferred_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred domains.",
                    },
                    "verdict": _enum(
                        "Sufficiency verdict (assess_evidence).",
                        ["sufficient", "gaps_remain", "exhausted_with_gaps"],
                    ),
                    "evidence_standard": {
                        "type": "object",
                        "properties": {
                            "risk_level": _enum("Risk.", ["exploratory", "normal", "high_stakes"]),
                            "minimum_independent_sources": {"type": "integer"},
                            "requires_authoritative_source": {"type": "boolean"},
                            "claim_types": {"type": "array", "items": {"type": "string"}},
                            "freshness_requirement": _enum(
                                "Freshness.", ["historical", "stable", "current", "latest"]
                            ),
                            "applicability_scope": _string("Scope (>=16 chars)."),
                            "stopping_rule": _string("Stop rule (>=20 chars)."),
                            "unresolved_uncertainties": {"type": "array", "items": {"type": "string"}},
                            "quality_checks": {"type": "array", "items": {"type": "object"}},
                        },
                        "description": "Evidence standard (assess_evidence).",
                    },
                    "facet_assessments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "facet": _string("Facet."),
                                "status": _enum("Status.", ["covered", "partial", "missing"]),
                                "source_ids": {"type": "array", "items": {"type": "string"}},
                                "evidence_quotes": {"type": "array", "items": {"type": "object"}},
                                "rationale": _string("Rationale (>=16 chars)."),
                            },
                        },
                        "description": "Per-facet judgments (assess_evidence).",
                    },
                    "title": _string("Title (import_url)."),
                    "name": _string("Alias of title."),
                    "folder": _string("Folder (import_url)."),
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["action"],
            },
            handler=_handle_web_fetch,
        ),
        ToolDefinition(
            name="learning_inspect",
            description="Inspect learning state: 'plan', 'truth', 'memory', or 'skills'.",
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum("Target.", ["plan", "truth", "memory", "skills"]),
                    "query": _string("Lookup query."),
                    "focus": _string("Focus topic (memory)."),
                    "section": _enum(
                        "Section (truth).",
                        ["all", "plan", "goal", "evidence", "progress", "mastery", "review", "practice"],
                    ),
                    "evidence_limit": {"type": "integer"},
                    "kind": _enum("Skill kind.", ["tutor", "knowledge", "action", "custom"]),
                },
                "required": ["action"],
            },
            handler=_handle_learning_inspect,
        ),
        ToolDefinition(
            name="learning_action",
            description=(
                "Governed learning actions: 'save_formal_plan', 'record_note', "
                "'specify_task', 'next_task', 'invoke_skill', or 'generate_image'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": _enum(
                        "Action.",
                        [
                            "save_formal_plan",
                            "record_note",
                            "specify_task",
                            "next_task",
                            "invoke_skill",
                            "generate_image",
                        ],
                    ),
                    "title": _string("Plan/image title."),
                    "summary": _string("Plan summary."),
                    "stages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": _string("Stage id."),
                                "title": _string("Stage title."),
                                "goal": _string("Stage goal."),
                                "outcomes": {"type": "array", "items": {"type": "string"}},
                                "resources": {"type": "array", "items": {"type": "string"}},
                                "status": _enum("Status.", ["pending", "active", "completed"]),
                            },
                            "required": ["title", "goal"],
                        },
                        "description": "Plan stages.",
                    },
                    "cadence": _string("Review cadence."),
                    "current_step": _string("First concrete step."),
                    "why_now": _string("Why now."),
                    "verify_method": {"type": "array", "items": {"type": "string"}},
                    "blocked_reason": _string("Blocker."),
                    "next_after_current": _string("Next step."),
                    "note": _string("Note text (record_note)."),
                    "content": _string("Alias of note."),
                    "kind": _string("Note kind."),
                    "natural_language_goal": _string("Task objective (specify_task)."),
                    "goal": _string("Alias of natural_language_goal."),
                    "focus_area": _string("Focus area (next_task)."),
                    "skill_id": _string("Skill id/name (invoke_skill)."),
                    "skill_name": _string("Alias of skill_id."),
                    "task_note": _string("Task context (invoke_skill)."),
                    "prompt": _string("Image description (generate_image) or task prompt."),
                    "style": _string("Image style (default 'diagram')."),
                    "aspect_ratio": _string("Aspect ratio (default '16:9')."),
                    "save_to_library": {"type": "boolean"},
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
