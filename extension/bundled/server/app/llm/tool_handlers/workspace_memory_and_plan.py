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

import asyncio
import fnmatch
import inspect
import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Literal, cast
from uuid import uuid4

from ...core.models import (
    LearningPlan,
    PlanStage,
)
from .organization_and_sandbox import (
    _handle_index_sandbox_file,
    _handle_write_sandbox_file,
    _sandbox_service,
)
from .registry_core import (
    ToolContext,
    _explicit_learning_note_request_allowed,
    _explicit_lecture_note_save_allowed,
    _leftover_training_persist_identity,
    _live_formal_plan_for_task_mint,
    _normalize_workspace_relpath,
    _persist_minted_task_on_sessions,
    _prefers_chinese,
    _resolve_workspace_root,
    _safe_path_under,
    _snapshot_file_list,
    _snapshot_file_listed,
    _snapshot_file_record,
    _snapshot_path_matches,
    _task_mint_tool_allowed,
    _workspace_file_snapshot,
)
from .search_and_research import (
    _validate_public_http_url,
)

logger = logging.getLogger("trainer.llm.tools")

_WORKSPACE_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        ".turbo",
        "dist",
        "build",
        "target",
        ".idea",
    }
)


def _is_ignored_workspace_relpath(rel_path: str) -> bool:
    parts = [part for part in rel_path.replace("\\", "/").split("/") if part and part != "."]
    return any(part in _WORKSPACE_IGNORED_DIRS for part in parts)


def _workspace_matches_pattern(rel_posix: str, pattern_raw: str) -> bool:
    normalized = rel_posix.strip("/")
    if not normalized:
        return False
    pattern = pattern_raw.strip() or "**/*"
    if pattern in {"**/*", "*", "**"}:
        return True
    if "/" not in pattern and "**" not in pattern:
        return fnmatch.fnmatch(PurePosixPath(normalized).name, pattern)
    return PurePosixPath(normalized).match(pattern) or fnmatch.fnmatch(normalized, pattern)


def _network_fetch_enabled(context: ToolContext) -> bool:
    runtime = getattr(context, "runtime", None)
    if runtime is None:
        return False
    research_flag = getattr(runtime, "research_network_fetch_enabled", None)
    if research_flag is not None:
        return bool(research_flag)
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is not None:
        return bool(getattr(resource_service, "enable_network_fetch", False))
    return False


async def _handle_web_search(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Search the public web (web results, Wikipedia, arXiv papers, GitHub repos)."""
    query = " ".join(str(args.get("query") or "").split()).strip()
    if not query:
        return {"ok": False, "error": "missing_query", "detail": "web_search requires a non-empty query."}
    if not _network_fetch_enabled(context):
        return {
            "ok": False,
            "error": "network_disabled",
            "detail": (
                "Live web search is disabled by Trainer settings (`trainer.research.networkEnabled`)."
            ),
        }
    try:
        limit = max(1, min(int(args.get("limit", 5)), 8))
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        limit = 5
    fetch_excerpts = args.get("fetch_excerpts", True) is not False

    from ...network_fetch import ControlledFetchError
    from ...research.web_search import WebSearchClient

    client = WebSearchClient(network_enabled=True, timeout=12)
    try:
        # Network I/O must not block the event loop: one slow search would
        # freeze every other request in this sidecar, including cancellations.
        hits = await asyncio.to_thread(client.search, query, limit=limit)
    except ControlledFetchError as exc:
        return {
            "ok": False,
            "error": exc.code,
            "detail": exc.detail,
            "query": query,
        }
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {
            "ok": False,
            "error": exc.__class__.__name__,
            "detail": str(exc),
            "query": query,
        }

    # If query explicitly asks for academic/research updates, include arXiv papers alongside web hits
    # when web results lacked arxiv/academic depth.
    lowered_q = query.lower()
    academic_intent = any(
        token in lowered_q
        for token in ("paper", "arxiv", "research", "论文", "研究", "进展", "模型", "world model", "survey")
    )
    if academic_intent and len(hits) < limit and not any(
        "arxiv.org" in str(item.get("url") or "") for item in hits
    ):
        try:
            extra_arxiv = await asyncio.to_thread(
                client._search_arxiv, query, limit=max(2, limit - len(hits))
            )
            seen_urls = {str(item.get("url") or "") for item in hits}
            for item in extra_arxiv:
                if item.get("url") not in seen_urls:
                    seen_urls.add(str(item.get("url") or ""))
                    hits.append({**item, "rank": len(hits) + 1})
                    if len(hits) >= limit:
                        break
        except Exception as exc:
            logger.debug("Supplementary arXiv web search failed: %s", exc)

    enriched: list[dict[str, Any]] = []
    for idx, hit in enumerate(hits[:limit]):
        entry = dict(hit)
        url = str(entry.get("url") or "").strip()
        if fetch_excerpts and idx < 3 and url and not str(entry.get("snippet") or "").strip():
            try:
                page = await asyncio.to_thread(client.fetch_page, url, max_length=1200)
                entry["snippet"] = page.get("content", "")
                entry["fetched_at"] = page.get("fetched_at", "")
                if page.get("final_url"):
                    entry["url"] = page["final_url"]
            except Exception as exc:
                logger.debug("Web search snippet enrichment skipped for %s: %s", url, exc)
        enriched.append(entry)

    is_zh = bool(context.response_language and context.response_language.lower().startswith("zh"))
    return {
        "ok": True,
        "query": query,
        "results": enriched,
        "items": enriched,
        "note": (
            f"检索到 {len(enriched)} 条公开网页/论文来源"
            if is_zh
            else f"Found {len(enriched)} public web sources"
        ),
    }


async def _handle_fetch_web_page(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read one public web page as bounded clean text without modifying the library."""
    url, validation_error = _validate_public_http_url(args.get("url"))
    if validation_error:
        return {
            "ok": False,
            "error": "invalid_url" if args.get("url") else "missing_url",
            "detail": validation_error,
        }
    assert url is not None
    if not _network_fetch_enabled(context):
        return {
            "ok": False,
            "error": "network_disabled",
            "detail": (
                "Live web page reading is disabled by Trainer settings (`trainer.research.networkEnabled`)."
            ),
        }
    try:
        max_chars = max(500, min(int(args.get("max_chars", 6000)), 12000))
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        max_chars = 6000

    from ...network_fetch import ControlledFetchError
    from ...research.web_search import WebSearchClient

    client = WebSearchClient(network_enabled=True, timeout=15)
    try:
        page = await asyncio.to_thread(client.fetch_page, url, max_length=max_chars)
    except ControlledFetchError as exc:
        try:
            response = await asyncio.to_thread(
                client._fetch_public_with_optional_proxy,
                url,
                headers={
                    "User-Agent": client._user_agent,
                    "Accept": "text/html,application/xhtml+xml,text/plain,application/json",
                },
            )
            raw_text = response.body.decode("utf-8", errors="ignore")
            content_type = response.headers.get("content-type", "text/html")
            extracted = (
                client._extract_text_from_html(raw_text, max_chars)
                if "html" in content_type.lower() or "<html" in raw_text.lower()
                else raw_text.strip()[:max_chars]
            )
            page = {
                "final_url": response.final_url,
                "fetched_at": response.fetched_at,
                "content_type": content_type,
                "content": extracted,
            }
        except Exception as inner_exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", inner_exc)
            return {"ok": False, "error": exc.code, "detail": exc.detail, "url": url}
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc), "url": url}

    content = str(page.get("content") or "").strip()
    lines = len(content.splitlines()) if content else 0
    return {
        "ok": True,
        "url": url,
        "final_url": page.get("final_url") or url,
        "fetched_at": page.get("fetched_at") or "",
        "content_type": page.get("content_type") or "",
        "content": content,
        "line_count": lines,
        "note": client._extract_domain(str(page.get("final_url") or url)),
    }


def _walk_workspace_files(
    root: Path,
    search_root: Path,
    pattern: str,
    *,
    max_depth: int | None,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Collect matching workspace paths on disk.

    Kept synchronous so the handler can run it with ``asyncio.to_thread``: a
    large tree walk on the event loop would stall every in-flight request.
    """
    collected: list[dict[str, Any]] = []
    total_seen = 0
    root_parts_count = len(search_root.resolve().parts)
    for current_dir, dirnames, filenames in os.walk(search_root, followlinks=False):
        current_path = Path(current_dir)
        rel_dir_parts = current_path.resolve().parts[root_parts_count:]
        current_depth = len(rel_dir_parts)
        # Prune ignored heavy/system directories before descending
        dirnames[:] = sorted(
            d for d in dirnames if d not in _WORKSPACE_IGNORED_DIRS
        )
        if max_depth is not None and current_depth >= max_depth:
            dirnames[:] = []
        for dirname in dirnames:
            full_dir = current_path / dirname
            rel_posix = str(full_dir.relative_to(root)).replace("\\", "/")
            if _workspace_matches_pattern(rel_posix, pattern):
                total_seen += 1
                if len(collected) < limit:
                    collected.append({"path": rel_posix, "is_dir": True, "size": 0})
        for filename in sorted(filenames):
            full_file = current_path / filename
            rel_posix = str(full_file.relative_to(root)).replace("\\", "/")
            if _is_ignored_workspace_relpath(rel_posix):
                continue
            if not _workspace_matches_pattern(rel_posix, pattern):
                continue
            try:
                stat = full_file.stat()
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                continue
            total_seen += 1
            if len(collected) < limit:
                collected.append(
                    {
                        "path": rel_posix,
                        "is_dir": False,
                        "size": stat.st_size,
                    }
                )
    return collected, total_seen


async def _handle_list_workspace_files(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    pattern_raw = str(args.get("pattern") or "**/*").strip() or "**/*"
    directory_raw = str(args.get("directory") or "").strip().replace("\\", "/").strip("/")
    if directory_raw in {".", ""}:
        directory_raw = ""
    raw_max_depth = args.get("max_depth")
    max_depth: int | None = None
    if raw_max_depth is not None:
        try:
            max_depth = max(1, min(int(raw_max_depth), 12))
        except Exception as exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            max_depth = None
    try:
        limit = max(1, min(int(args.get("limit", 120)), 400))
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        limit = 120
    root = _resolve_workspace_root(context)
    if pattern_raw.startswith("/") or directory_raw.startswith("/"):
        return {
            "ok": False,
            "error": "absolute_pattern_rejected",
            "detail": "Pattern and directory must be relative to the workspace root.",
        }
    if root is not None:
        search_root = _safe_path_under(root, directory_raw) if directory_raw else root
        if search_root is None or not search_root.is_dir():
            return {
                "ok": False,
                "error": "directory_not_found",
                "detail": f"Directory {directory_raw or '.'!r} does not exist in the workspace.",
            }
        # If pattern includes a leading directory prefix like "src/**/*" and directory wasn't set,
        # keep walking pruned tree cleanly.
        try:
            collected, total_seen = await asyncio.to_thread(
                _walk_workspace_files,
                root,
                search_root,
                pattern_raw,
                max_depth=max_depth,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        return {
            "ok": True,
            "pattern": pattern_raw,
            "directory": directory_raw or ".",
            "items": collected,
            "total_seen": total_seen,
            "truncated": total_seen > len(collected),
            "source": "workspace_disk",
        }
    snapshot_items = _snapshot_file_list(context)
    if not snapshot_items:
        return {
            "ok": False,
            "error": "no_workspace",
            "detail": "No workspace path is currently available; the learner has not opened a folder.",
        }
    filtered = []
    for item in snapshot_items:
        rel_path = str(item.get("path") or "").replace("\\", "/")
        if _is_ignored_workspace_relpath(rel_path):
            continue
        if directory_raw and not (rel_path == directory_raw or rel_path.startswith(directory_raw + "/")):
            continue
        if _snapshot_path_matches(rel_path, pattern_raw):
            filtered.append(item)
    return {
        "ok": True,
        "pattern": pattern_raw,
        "directory": directory_raw or ".",
        "items": filtered[:limit],
        "total_seen": len(filtered),
        "truncated": len(filtered) > limit,
        "source": "workspace_snapshot",
    }


async def _import_single_workspace_item(
    context: ToolContext,
    path_raw: str,
    *,
    folder: str = "",
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
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
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc), "path": relative}
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
                "path": relative,
                "detail": f"Path {path_raw!r} is not available in the host workspace snapshot.",
            }
        text = str(record.get("content") or "")
        relative = str(record.get("path") or relative)
    if not text.strip():
        return {"ok": False, "error": "empty_file", "path": relative, "detail": f"Path {relative!r} has no importable text."}
    safe_folder = "/".join(
        part.strip()
        for part in folder.replace("\\", "/").split("/")
        if part.strip() and part.strip() not in {".", ".."}
    )
    dest = (
        f"sources/workspace/{safe_folder}/{Path(relative).name}"
        if safe_folder
        else f"sources/workspace/{relative.lstrip('/')}"
    )
    written = await _handle_write_sandbox_file(context, {"path": dest, "content": text, "create": True})
    if written.get("ok") is not True:
        return written
    base_tags = ["workspace", "remote"] if _workspace_file_snapshot(context).get("is_remote") else ["workspace"]
    if safe_folder:
        base_tags.append(safe_folder)
    for tag in (extra_tags or []):
        clean_tag = str(tag).strip()
        if clean_tag and clean_tag not in base_tags:
            base_tags.append(clean_tag)
    indexed = await _handle_index_sandbox_file(
        context,
        {
            "path": dest,
            "name": Path(relative).name,
            "tags": base_tags[:20],
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
        "note": relative,
    }


async def _handle_import_workspace_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Selectively copy one or more learner-project files/folders into the local Trainer library."""
    folder = str(args.get("folder") or args.get("folder_path") or "").strip()
    raw_tags = args.get("tags")
    extra_tags = (
        [str(tag).strip() for tag in raw_tags if str(tag).strip()][:12]
        if isinstance(raw_tags, list)
        else []
    )
    raw_paths = args.get("paths")
    directory_raw = str(args.get("directory") or "").strip().replace("\\", "/").strip("/")
    path_raw = str(args.get("path") or "").strip()

    if isinstance(raw_paths, list) and raw_paths:
        target_paths = [str(p).strip() for p in raw_paths if str(p).strip()][:30]
    elif directory_raw:
        listed = await _handle_list_workspace_files(
            context,
            {"directory": directory_raw, "pattern": "**/*", "limit": 60},
        )
        if not listed.get("ok"):
            return listed
        target_paths = [
            str(item.get("path") or "")
            for item in (listed.get("items") or [])
            if isinstance(item, dict) and not item.get("is_dir") and item.get("path")
        ][:30]
        if not target_paths:
            return {
                "ok": False,
                "error": "empty_directory",
                "detail": f"No importable text files were found under {directory_raw!r}.",
            }
    elif path_raw:
        return await _import_single_workspace_item(
            context,
            path_raw,
            folder=folder,
            extra_tags=extra_tags,
        )
    else:
        return {
            "ok": False,
            "error": "missing_path",
            "detail": "import_workspace_file requires a path, paths array, or directory.",
        }

    imported_items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in target_paths:
        outcome = await _import_single_workspace_item(
            context,
            candidate,
            folder=folder,
            extra_tags=extra_tags,
        )
        if outcome.get("ok") is True:
            imported_items.append(outcome)
        else:
            skipped.append({"path": candidate, "error": outcome.get("error"), "detail": outcome.get("detail")})
    if not imported_items:
        return {
            "ok": False,
            "error": skipped[0].get("error") if skipped else "import_failed",
            "detail": skipped[0].get("detail") if skipped else "No files were imported.",
            "skipped": skipped,
        }
    return {
        "ok": True,
        "imported": True,
        "imported_count": len(imported_items),
        "imported_items": imported_items,
        "skipped": skipped,
        "note": f"{len(imported_items)} files",
    }


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
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
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
        except Exception as exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
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
        structured_getter = getattr(memory_service, "structured_for_workspace", None)
        if callable(structured_getter):
            try:
                import hashlib

                structured = cast(Any, structured_getter(context.workspace_id))
                signal_key = f"{kind}:{hashlib.sha1(note.encode('utf-8')).hexdigest()[:10]}"
                structured.remember_teaching_signal(
                    signal_key,
                    note,
                    source="coach",
                )
                if context.session_id and hasattr(structured, "add_session_highlight"):
                    structured.add_session_highlight(context.session_id, note)
                persist_fn = getattr(memory_service, "_persist_structured", None)
                if callable(persist_fn):
                    persist_fn(context.workspace_id)
                return {"ok": True, "kind": kind, "note": note}
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
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
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {"ok": True, "kind": kind, "note": note}


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
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    if plan is None:
        return {"ok": True, "plan": None, "summary": "no plan exists for this workspace yet"}
    payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
    summary = _summarize_plan(payload)
    return {"ok": True, "plan": payload, "summary": summary}


_TRUTH_OPAQUE_ID_KEYS = frozenset(
    {
        "id",
        "goal_id",
        "plan_id",
        "stage_id",
        "current_stage_id",
        "card_id",
        "attempt_id",
        "resource_id",
        "session_id",
        "workspace_id",
        "evidence_id",
        "selected_card_id",
        "active_card_id",
        "anchor_id",
    }
)


def _localize_truth_enum(value: Any, *, is_zh: bool) -> Any:
    if not isinstance(value, str):
        return value
    mappings = {
        "insufficient_evidence": ("暂无足够验证证据", "not enough verified evidence yet"),
        "no_recall_evidence": ("尚未通过主动回想检验", "no recall check recorded yet"),
        "not_verified": ("未验证", "not verified"),
        "needs_review": ("待巩固", "needs review"),
        "assisted": ("需辅助", "assisted"),
        "independent": ("独立完成", "independent"),
        "repeat_verified": ("稳定掌握", "repeat verified"),
        "completed": ("已完成", "completed"),
        "done": ("已完成", "completed"),
        "active": ("进行中", "active"),
        "paused": ("已暂停", "paused"),
        "pending": ("待开始", "pending"),
        "known": ("已有真实证据", "verified"),
    }
    pair = mappings.get(value.strip().lower())
    if pair is not None:
        return pair[0] if is_zh else pair[1]
    return value


def _sanitize_learning_truth_value(value: Any, *, is_zh: bool) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _TRUTH_OPAQUE_ID_KEYS:
                continue
            cleaned[key_text] = _sanitize_learning_truth_value(item, is_zh=is_zh)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_learning_truth_value(item, is_zh=is_zh) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(
            r"(?:goal|resource|card|stage|plan|attempt|evidence|session|ctx|ws)-[0-9a-zA-Z_-]{6,}",
            stripped,
        ):
            return ""
        return _localize_truth_enum(value, is_zh=is_zh)
    return value


def _summarize_plan(payload: Any, *, is_zh: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    stages = [stage for stage in (payload.get("stages") or []) if isinstance(stage, dict)]
    completed_stages = [
        {
            "title": stage.get("title"),
            "goal": stage.get("goal"),
            "status": _localize_truth_enum(str(stage.get("status") or ""), is_zh=is_zh),
        }
        for stage in stages
        if str(stage.get("status") or "").strip().lower() in {"done", "completed"}
    ]
    raw_active = next(
        (stage for stage in stages if str(stage.get("status") or "").strip().lower() == "active"),
        None,
    )
    active = (
        {
            "title": raw_active.get("title"),
            "goal": raw_active.get("goal"),
            "status": _localize_truth_enum(str(raw_active.get("status") or ""), is_zh=is_zh),
        }
        if isinstance(raw_active, dict)
        else None
    )
    upcoming_stages = [
        {
            "title": stage.get("title"),
            "goal": stage.get("goal"),
            "status": _localize_truth_enum(str(stage.get("status") or ""), is_zh=is_zh),
        }
        for stage in stages
        if str(stage.get("status") or "").strip().lower() not in {"done", "completed", "active"}
    ]
    return {
        "title": payload.get("title"),
        "stage_count": len(stages),
        "completed_stage_count": len(completed_stages),
        "completed_stages": completed_stages,
        "active_stage": active,
        "upcoming_stages": upcoming_stages,
        "next_step": payload.get("next_step"),
    }


def _slug_markdown_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f\r\n\t]+', " ", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned).strip(".-")
    if not cleaned:
        cleaned = "lecture-note"
    if len(cleaned) > 72:
        cleaned = cleaned[:72].rstrip(".-")
    return cleaned if cleaned.lower().endswith(".md") else f"{cleaned}.md"


async def _handle_inspect_learning_truth(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Read-only unified view of plan stages, capability evidence, reviews, and active goal."""
    runtime = context.runtime
    workspace_id = context.workspace_id
    is_zh = _prefers_chinese(context.response_language)
    section = str(args.get("section") or "all").strip().lower() or "all"
    try:
        evidence_limit = max(1, min(int(args.get("evidence_limit") or 20), 50))
    except (TypeError, ValueError):
        evidence_limit = 20

    result: dict[str, Any] = {
        "ok": True,
        "section": section,
        "presentation_rule": (
            "只用自然中文向学习者转述下方事实；严禁输出英文字段名、下划线状态码或内部编号。"
            if is_zh
            else "Summarize the facts below in natural prose; never print raw JSON key names, snake_case enum tokens, or opaque IDs."
        ),
    }

    repository = getattr(runtime, "repository", None)
    memory_service = getattr(runtime, "memory_service", None)
    learner_state_service = getattr(runtime, "learner_state_service", None)

    if section in {"all", "plan", "goal"} and repository is not None:
        if hasattr(repository, "get_current_goal"):
            try:
                goal = repository.get_current_goal(workspace_id)
                if goal is not None and hasattr(goal, "model_dump"):
                    raw_goal = _sanitize_learning_truth_value(goal.model_dump(mode="json"), is_zh=is_zh)
                    result["active_goal"] = raw_goal
                else:
                    result["active_goal"] = None
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                result["active_goal_error"] = str(exc)
        if hasattr(repository, "get_latest_plan"):
            try:
                plan = repository.get_latest_plan(workspace_id)
                if plan is None:
                    result["plan"] = None
                else:
                    plan_payload = plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan
                    stages_raw = plan_payload.get("stages") if isinstance(plan_payload, dict) else []
                    sanitized_stages = _sanitize_learning_truth_value(stages_raw or [], is_zh=is_zh)
                    result["plan"] = {
                        "summary": _summarize_plan(plan_payload, is_zh=is_zh),
                        "stages": sanitized_stages,
                    }
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                result["plan_error"] = str(exc)

    if section in {"all", "evidence", "progress", "mastery"}:
        if learner_state_service is not None and hasattr(learner_state_service, "snapshot"):
            try:
                state_payload = learner_state_service.snapshot(
                    workspace_id,
                    evidence_limit=evidence_limit,
                ).to_payload()
                if isinstance(state_payload, dict):
                    for key in ("projection", "capabilities", "mastery", "evidence", "summary", "counts"):
                        if key in state_payload and state_payload[key] is not None:
                            result[f"learner_{key}"] = _sanitize_learning_truth_value(
                                state_payload[key],
                                is_zh=is_zh,
                            )
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                result["learner_state_error"] = str(exc)
        if memory_service is not None:
            try:
                from ...learner_state import collect_unified_evidence

                unified = collect_unified_evidence(
                    memory_service=memory_service,
                    attempt_store=getattr(runtime, "attempt_store", None),
                    workspace_id=workspace_id,
                    limit=evidence_limit,
                )
                result["evidence_records"] = [
                    _sanitize_learning_truth_value(
                        item.model_dump(mode="json") if hasattr(item, "model_dump") else item,
                        is_zh=is_zh,
                    )
                    for item in unified
                ]
                result["verified_evidence_count"] = len(result["evidence_records"])
            except Exception as exc:
                logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
                result["evidence_error"] = str(exc)

    if section in {"all", "review", "practice"} and memory_service is not None:
        try:
            snapshot = memory_service.snapshot(workspace_id)
            snap_data = snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else {}
            due_reviews = _sanitize_learning_truth_value(
                snap_data.get("due_reviews") or [],
                is_zh=is_zh,
            )
            result["due_reviews"] = due_reviews
            result["weaknesses"] = _sanitize_learning_truth_value(
                snap_data.get("weaknesses") or [],
                is_zh=is_zh,
            )
            result["current_focus"] = snap_data.get("current_focus") or ""
            result["learning_outcomes"] = _sanitize_learning_truth_value(
                (snap_data.get("learning_outcomes") or [])[-8:],
                is_zh=is_zh,
            )
            get_cards = getattr(memory_service, "get_cards", None)
            if callable(get_cards):
                raw_cards = get_cards(workspace_id)
                cards = list(raw_cards) if isinstance(raw_cards, (list, tuple, set)) else []
                active_cards = [
                    {
                        "title": getattr(card, "title", ""),
                        "focus_area": getattr(card, "focus_area", ""),
                        "problem_statement": getattr(card, "problem_statement", ""),
                        "status": _localize_truth_enum(
                            str(getattr(card, "status", "") or ""),
                            is_zh=is_zh,
                        ),
                    }
                    for card in cards
                    if getattr(card, "status", "") not in {"archived", "completed"}
                ][:5]
                result["active_practice_cards"] = active_cards
        except Exception as exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
            result["memory_error"] = str(exc)

    return result


async def _handle_save_lecture_note(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Save a structured RethinkFun Markdown lecture note into `<LibraryRoot>/Trainer Library/`."""
    if not _explicit_lecture_note_save_allowed(context):
        return {
            "ok": False,
            "error": "explicit_lecture_note_save_required",
            "detail": (
                "save_lecture_note is only available when the learner explicitly asked "
                "to save a lecture or study note into their library."
            ),
        }
    runtime = context.runtime
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "resource_service is unavailable."}

    title = " ".join(str(args.get("title") or "").split()).strip()
    markdown_content = str(args.get("markdown_content") or "").strip()
    if not title:
        return {"ok": False, "error": "missing_title", "detail": "title must be non-empty."}
    if not markdown_content:
        return {"ok": False, "error": "missing_content", "detail": "markdown_content must be non-empty."}

    is_zh = _prefers_chinese(context.response_language)
    default_folder = "学习讲稿" if is_zh else "Lecture Notes"
    folder = " ".join(str(args.get("folder") or "").split()).strip() or default_folder
    tags = _tool_text_list(args.get("tags"), limit=8, item_limit=48)
    if "lecture-note" not in tags:
        tags.append("lecture-note")

    filename = _slug_markdown_filename(title)
    if not markdown_content.lstrip().startswith("#"):
        markdown_content = f"# {title}\n\n{markdown_content}\n"

    memory_service = getattr(runtime, "memory_service", None)
    if memory_service is not None:
        try:
            workspace_meta = memory_service.snapshot(context.workspace_id).workspace
            if isinstance(workspace_meta, dict) and workspace_meta.get("workspace_trusted") is False:
                return {
                    "ok": False,
                    "error": "library_not_writable",
                    "detail": "Workspace is untrusted.",
                }
        except Exception as exc:
            logger.debug("Workspace trust metadata check skipped in save_lecture_note: %s", exc)

    from ...core.models import ResourceIndexRequest, ResourceUploadRequest
    from ...resources.library import LIBRARY_DIRECTORY_NAME, LibraryError, LibraryService
    from ...workspace.authority import PermissionLevel, WorkspaceAuthority

    repository = getattr(runtime, "repository", None)
    carrier_resolver = cast(
        Callable[[str], WorkspaceAuthority | None] | None,
        getattr(runtime, "library_carrier_authority", None),
    )
    library_download = None
    saved_abs_path: Path | None = None
    actual_folder = folder
    library_service: LibraryService | None = None

    if repository is not None and carrier_resolver is not None and callable(carrier_resolver):
        carrier_authority: WorkspaceAuthority | None = carrier_resolver(context.workspace_id)
        project_root = (
            runtime.resolve_workspace_path(context.workspace_id)
            if hasattr(runtime, "resolve_workspace_path")
            else None
        )
        project_resolved = (
            Path(str(project_root)).expanduser().resolve(strict=False)
            if project_root
            else None
        )
        resolved_library_root = (
            resource_service._resolved_library_root(context.workspace_id)
            if hasattr(resource_service, "_resolved_library_root")
            else None
        )
        lib_candidate = (
            Path(resolved_library_root).expanduser().resolve(strict=False)
            if resolved_library_root is not None
            else None
        )
        if (lib_candidate is None or lib_candidate == project_resolved) and not (
            carrier_authority is not None and carrier_authority.is_remote_workspace
        ):
            sb_service = _sandbox_service(context)
            if sb_service is not None:
                try:
                    sb_root = Path(sb_service.ensure_operation_root(context.workspace_id)).expanduser().resolve(strict=False)
                    if sb_root.is_dir() and sb_root != project_resolved:
                        lib_candidate = sb_root
                except Exception as exc:
                    logger.debug("Sandbox operation root probe skipped: %s", exc)
        effective_resolver: Callable[[str], WorkspaceAuthority | None] = carrier_resolver
        if (
            (
                carrier_authority is None
                or not carrier_authority.has_active_workspace_root
                or carrier_authority.destructive_mutation_block_reason() is not None
                or (
                    project_resolved is not None
                    and Path(str(carrier_authority.active_workspace_root)).expanduser().resolve(strict=False)
                    == project_resolved
                )
            )
            and lib_candidate is not None
            and lib_candidate.is_dir()
            and lib_candidate != project_resolved
        ):
            dedicated_carrier = WorkspaceAuthority(
                root_path=str(lib_candidate),
                initial_permission=PermissionLevel.INSPECT,
            )
            dedicated_carrier.set_workspace_context(workspace_trusted=True)

            def _resolve_dedicated_carrier(
                _ws: str,
                _auth: WorkspaceAuthority = dedicated_carrier,
            ) -> WorkspaceAuthority | None:
                return _auth

            effective_resolver = _resolve_dedicated_carrier
        library_service = LibraryService(
            repository,
            workspace_authority_resolver=effective_resolver,
        )
        try:
            library_download, saved_abs_path = library_service.save_markdown_note(
                context.workspace_id,
                filename=filename,
                markdown_content=markdown_content,
                folder=folder,
            )
        except LibraryError as first_exc:
            # Retry with the safe default folder if a model supplied an invalid folder name.
            if folder != default_folder:
                try:
                    library_download, saved_abs_path = library_service.save_markdown_note(
                        context.workspace_id,
                        filename=filename,
                        markdown_content=markdown_content,
                        folder=default_folder,
                    )
                    actual_folder = default_folder
                except LibraryError as exc:
                    return {"ok": False, "error": exc.code, "detail": exc.message(context.response_language)}
            else:
                return {
                    "ok": False,
                    "error": first_exc.code,
                    "detail": first_exc.message(context.response_language),
                }
        if library_download is not None:
            parts = library_download.relative_path.split("/")
            if len(parts) >= 3 and parts[0] == LIBRARY_DIRECTORY_NAME:
                actual_folder = "/".join(parts[1:-1]) or default_folder

    if saved_abs_path is not None and library_download is not None:
        upload_req = ResourceUploadRequest(
            workspace_id=context.workspace_id,
            kind="markdown",
            name=saved_abs_path.name,
            source=str(saved_abs_path),
            tags=tags,
            source_type="file",
            content_language=context.response_language,
        )
    else:
        upload_req = ResourceUploadRequest(
            workspace_id=context.workspace_id,
            kind="markdown",
            name=filename,
            source=filename,
            content=markdown_content,
            content_encoding="utf-8",
            tags=tags,
            source_type="file",
            content_language=context.response_language,
        )
    try:
        if saved_abs_path is not None and library_service is not None:
            carrier_root_str = str(library_service.workspace_root(context.workspace_id))
            try:
                uploaded = resource_service.upload(
                    context.workspace_id,
                    upload_req,
                    workspace_path=carrier_root_str,
                )
            except TypeError:
                uploaded = resource_service.upload(context.workspace_id, upload_req)
        else:
            uploaded = resource_service.upload(context.workspace_id, upload_req)
        indexed = resource_service.index(
            context.workspace_id,
            ResourceIndexRequest(workspace_id=context.workspace_id, resource_id=uploaded.id),
        )
        if library_service is not None and library_download is not None:
            library_service.remember_download(context.workspace_id, indexed, library_download)
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}

    saved_path = (
        library_download.relative_path
        if library_download is not None
        else f"{LIBRARY_DIRECTORY_NAME}/{actual_folder}/{indexed.name}"
    )
    return {
        "ok": True,
        "title": title,
        "name": indexed.name,
        "folder": actual_folder,
        "saved_path": saved_path,
        "status": getattr(indexed, "status", "indexed"),
        "stored_under_library_root": True,
        "exact_path_instruction": (
            f"讲稿已真实写入 `{saved_path}`。提及保存位置时必须原样引用 `{saved_path}`，不得猜测或改写路径。"
            if is_zh
            else f"Saved to `{saved_path}`. Cite `{saved_path}` verbatim if mentioning the saved path; never invent or alter the filename."
        ),
    }


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


def _explicit_formal_plan_stage_count(message: object) -> int | None:
    text = str(message or "").lower()
    chinese_counts = {char: index for index, char in enumerate("一二三四五六七八九十", 1)}
    counts: set[int] = set()
    for match in re.finditer(r"(?<![\d第])([1-9]|1[0-2]|[一二三四五六七八九十])\s*个?\s*阶段", text):
        value = match.group(1)
        counts.add(int(value) if value.isdigit() else chinese_counts[value])
    for match in re.finditer(r"\b(1[0-2]|[1-9])\s*[- ]?\s*stages?\b", text):
        counts.add(int(match.group(1)))
    return next(iter(counts)) if len(counts) == 1 else None


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
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    leftover_plan, leftover_runtime, _leftover_task = _leftover_training_persist_identity(context)
    from ...core.workspace_live_identity import (
        is_formal_plan_live_for_fill as leftover_formal_plan_is_live_for_fill,
    )
    from ...core.workspace_scope_runtime import leftover_formal_plan_identity_labels

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
    if len(stages) != len(raw_stages):
        return {
            "ok": False,
            "error": "invalid_stages",
            "detail": "Every requested stage must have a title and goal; do not save a partial plan.",
        }
    stage_count = _explicit_formal_plan_stage_count(context.extra.get("learner_message"))
    if stage_count is not None and len(stages) != stage_count:
        return {
            "ok": False,
            "error": "stage_count_mismatch",
            "expected_stage_count": stage_count,
            "actual_stage_count": len(stages),
            "detail": "Include every stage requested by the learner before saving the formal plan.",
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
        from ...training.plan_revision import save_plan_advancing_revision

        save_plan_advancing_revision(repository, context.workspace_id, plan)
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
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {
        "ok": True,
        "committed": True,
        "plan": plan.model_dump(mode="json"),
        "summary": _summarize_plan(plan.model_dump(mode="json")),
    }


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
    from ...core.models import TaskSpecifyRequest

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
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
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
        except Exception as exc:
            logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
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
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    return {
        "ok": True,
        "committed": True,
        "task": task.model_dump(mode="json"),
        "plan_id": plan_id,
    }


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
    if root is None:
        return {
            "ok": False,
            "error": "workspace_root_required",
            "detail": "No workspace root is configured for diagnostics.",
        }
    target = _safe_path_under(root, path_raw)
    if target is None or not target.is_file():
        return {"ok": False, "error": "not_found", "detail": f"{path_raw!r} is not a readable file."}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
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


async def _handle_search_academic_papers(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Search arXiv academic papers (and optionally GitHub repos) for a topic."""
    query = " ".join(str(args.get("query") or "").split()).strip()
    if not query:
        return {
            "ok": False,
            "error": "missing_query",
            "detail": "search_academic_papers requires a non-empty query.",
        }
    if not _network_fetch_enabled(context):
        return {
            "ok": False,
            "error": "network_disabled",
            "detail": (
                "Live web search is disabled by Trainer settings (`trainer.research.networkEnabled`)."
            ),
        }
    try:
        limit = max(1, min(int(args.get("limit", 5)), 8))
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        limit = 5
    include_github = args.get("include_github", False) is True

    from ...research.web_search import WebSearchClient

    client = WebSearchClient(network_enabled=True, timeout=12)
    try:
        results = await asyncio.to_thread(client._search_arxiv, query, limit=limit)
    except Exception as exc:
        logger.debug("Suppressed exception in workspace_memory_and_plan: %s", exc)
        return {
            "ok": False,
            "error": exc.__class__.__name__,
            "detail": str(exc),
            "query": query,
        }
    if include_github and len(results) < limit:
        try:
            extra = await asyncio.to_thread(
                client._search_github, query, limit=max(1, min(3, limit - len(results)))
            )
            for item in extra:
                results.append({**item, "rank": len(results) + 1})
        except Exception as exc:
            logger.debug("Supplementary GitHub search failed: %s", exc)
    return {
        "ok": True,
        "query": query,
        "results": results[:limit],
        "items": results[:limit],
        "count": len(results[:limit]),
    }


def _resolve_tool_library_service(
    context: ToolContext,
    *,
    require_writable: bool = False,
) -> tuple[Any | None, dict[str, Any] | None]:
    """Build a LibraryService scoped strictly to `<LibraryRoot>` / inline managed library."""
    runtime = context.runtime
    if runtime is None:
        return None, {"ok": False, "error": "runtime_unavailable", "detail": "Trainer runtime is unavailable."}
    repository = getattr(runtime, "repository", None)
    resource_service = getattr(runtime, "resource_service", None)
    if repository is None or resource_service is None:
        return None, {"ok": False, "error": "library_unavailable", "detail": "Resource library service is unavailable."}

    from ...resources.library import LibraryService
    from ...workspace.authority import PermissionLevel, WorkspaceAuthority

    carrier_resolver = cast(
        Callable[[str], WorkspaceAuthority | None] | None,
        getattr(runtime, "library_carrier_authority", None),
    )
    effective_resolver: Callable[[str], WorkspaceAuthority | None] | None = carrier_resolver
    carrier = carrier_resolver(context.workspace_id) if callable(carrier_resolver) else None
    project_raw = (
        runtime.resolve_workspace_path(context.workspace_id)
        if hasattr(runtime, "resolve_workspace_path")
        else None
    )
    project_resolved = Path(str(project_raw)).expanduser().resolve(strict=False) if project_raw else None
    resolved_lib_raw = (
        resource_service._resolved_library_root(context.workspace_id)
        if hasattr(resource_service, "_resolved_library_root")
        else None
    )
    lib_candidate = (
        Path(str(resolved_lib_raw)).expanduser().resolve(strict=False)
        if resolved_lib_raw
        else None
    )
    if (lib_candidate is None or lib_candidate == project_resolved) and not (
        carrier is not None and carrier.is_remote_workspace
    ):
        memory_service = getattr(runtime, "memory_service", None)
        explicitly_blocked = False
        if memory_service is not None:
            try:
                ws_meta = memory_service.snapshot(context.workspace_id).workspace
                if isinstance(ws_meta, dict) and (
                    ws_meta.get("workspace_trusted") is False
                    or ws_meta.get("is_remote_workspace") is True
                    or bool(str(ws_meta.get("remote_name") or "").strip())
                ):
                    explicitly_blocked = True
            except Exception as exc:
                logger.debug("Library workspace trust check skipped: %s", exc)
        if not explicitly_blocked:
            sb_service = _sandbox_service(context)
            if sb_service is not None:
                try:
                    sb_root = Path(sb_service.ensure_operation_root(context.workspace_id)).expanduser().resolve(strict=False)
                    if sb_root.is_dir() and sb_root != project_resolved:
                        lib_candidate = sb_root
                except Exception as exc:
                    logger.debug("Sandbox operation root probe skipped: %s", exc)
    if (
        (
            carrier is None
            or not carrier.has_active_workspace_root
            or carrier.destructive_mutation_block_reason() is not None
            or (
                project_resolved is not None
                and Path(str(carrier.active_workspace_root)).expanduser().resolve(strict=False)
                == project_resolved
            )
        )
        and lib_candidate is not None
        and lib_candidate.is_dir()
        and lib_candidate != project_resolved
    ):
        dedicated = WorkspaceAuthority(
            root_path=str(lib_candidate),
            initial_permission=PermissionLevel.INSPECT,
        )
        dedicated.set_workspace_context(workspace_trusted=True)

        def _resolve_dedicated(_ws: str, _auth: WorkspaceAuthority = dedicated) -> WorkspaceAuthority | None:
            return _auth

        effective_resolver = _resolve_dedicated

    if not callable(effective_resolver):
        if require_writable:
            return None, {
                "ok": False,
                "error": "library_root_unavailable",
                "detail": "Bind or create a Trainer Library folder before organizing folders.",
            }
        return None, None

    library_service = LibraryService(
        repository,
        workspace_authority_resolver=effective_resolver,
        inline_resource_root_resolver=getattr(resource_service, "_inline_resource_root", None),
    )
    return library_service, None


async def _handle_list_library_folders(
    context: ToolContext,
    _args: dict[str, Any],
) -> dict[str, Any]:
    """List Trainer Library folders and resource group counts."""
    runtime = context.runtime
    repository = getattr(runtime, "repository", None)
    list_resources_fn = getattr(repository, "list_resources", None)
    if not callable(list_resources_fn):
        return {"ok": False, "error": "library_unavailable", "detail": "Resource repository is unavailable."}

    from ...resources.library import LIBRARY_DIRECTORY_NAME, LibraryError

    resources = list(cast("Iterable[Any]", list_resources_fn(context.workspace_id)) or [])
    uncategorized_count = sum(
        1 for item in resources if not str(getattr(item, "collection_path", "") or "").strip()
    )
    library_service, _err = _resolve_tool_library_service(context, require_writable=False)
    if library_service is not None:
        try:
            snap = library_service.list_groups(context.workspace_id)
            groups_payload = [
                {
                    "path": node.get("path") if isinstance(node, dict) else node.path,
                    "name": node.get("name") if isinstance(node, dict) else node.name,
                    "workspace_path": (
                        node.get("workspace_path")
                        if isinstance(node, dict) and node.get("workspace_path")
                        else f"{LIBRARY_DIRECTORY_NAME}/{node.get('path') if isinstance(node, dict) else node.path}"
                    ),
                    "resource_count": (
                        node.get("resource_count", 0)
                        if isinstance(node, dict)
                        else node.resource_count
                    ),
                }
                for node in _flatten_library_group_nodes(snap.groups)
            ]
            return {
                "ok": True,
                "managed_root": snap.managed_root,
                "exists": snap.exists,
                "total_resource_count": snap.total_resource_count,
                "uncategorized_count": uncategorized_count,
                "groups": groups_payload,
            }
        except LibraryError:
            pass

    group_counts: dict[str, int] = {}
    for item in resources:
        group = str(getattr(item, "collection_path", "") or "").strip().strip("/")
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
    return {
        "ok": True,
        "managed_root": LIBRARY_DIRECTORY_NAME,
        "exists": bool(group_counts),
        "total_resource_count": len(resources),
        "uncategorized_count": uncategorized_count,
        "groups": [
            {
                "path": path,
                "name": path.rsplit("/", 1)[-1],
                "workspace_path": f"{LIBRARY_DIRECTORY_NAME}/{path}",
                "resource_count": count,
            }
            for path, count in sorted(group_counts.items())
        ],
    }


def _flatten_library_group_nodes(nodes: Iterable[Any]) -> list[Any]:
    flat: list[Any] = []
    for node in nodes or ():
        flat.append(node)
        children = (
            node.get("children")
            if isinstance(node, dict)
            else getattr(node, "children", None)
        )
        if children:
            flat.extend(_flatten_library_group_nodes(children))
    return flat


async def _handle_curate_library_resources(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Create/rename library folders or regroup/rename/tag resources inside Trainer Library."""
    action = str(args.get("action") or "").strip().lower()
    folder_path = str(args.get("folder_path") or "").strip()
    new_folder_path = str(args.get("new_folder_path") or "").strip()
    resource_id = str(args.get("resource_id") or "").strip()
    title = str(args.get("title") or "").strip()
    raw_tags = args.get("tags")

    runtime = context.runtime
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is None:
        return {"ok": False, "error": "library_unavailable", "detail": "Resource service is unavailable."}

    from ...core.models import ResourceOrganizeRequest
    from ...resources.library import LibraryError

    if action in {"create_folder", "rename_folder"}:
        library_service, err = _resolve_tool_library_service(context, require_writable=True)
        if err is not None:
            return err
        assert library_service is not None
        try:
            if action == "create_folder":
                if not folder_path:
                    return {"ok": False, "error": "missing_folder_path", "detail": "create_folder requires folder_path."}
                result = library_service.create_group(context.workspace_id, folder_path)
                return {"ok": True, "action": action, **result}
            if not folder_path or not new_folder_path:
                return {
                    "ok": False,
                    "error": "missing_folder_path",
                    "detail": "rename_folder requires folder_path and new_folder_path.",
                }
            result = library_service.rename_group(context.workspace_id, folder_path, new_folder_path)
            return {"ok": True, "action": action, **result}
        except LibraryError as exc:
            return {
                "ok": False,
                "error": exc.code,
                "detail": exc.message(context.response_language),
            }

    if action not in {"move_to_folder", "rename_resource", "tag_resource"}:
        return {
            "ok": False,
            "error": "unsupported_action",
            "detail": (
                "action must be one of create_folder, rename_folder, "
                "move_to_folder, rename_resource, tag_resource."
            ),
        }
    if not resource_id:
        return {"ok": False, "error": "missing_resource_id", "detail": f"{action} requires resource_id."}

    try:
        if action == "move_to_folder":
            req = ResourceOrganizeRequest(
                workspace_id=context.workspace_id,
                resource_id=resource_id,
                action="set_group",
                group=folder_path,
            )
        elif action == "rename_resource":
            if not title:
                return {"ok": False, "error": "missing_title", "detail": "rename_resource requires title."}
            req = ResourceOrganizeRequest(
                workspace_id=context.workspace_id,
                resource_id=resource_id,
                action="rename",
                title=title,
            )
        else:
            tags = [str(item).strip() for item in (raw_tags or []) if str(item).strip()] if isinstance(raw_tags, list) else []
            req = ResourceOrganizeRequest(
                workspace_id=context.workspace_id,
                resource_id=resource_id,
                action="set_tags",
                tags=tags,
            )
        updated = resource_service.organize_resource(context.workspace_id, req)
    except (KeyError, ValueError, PermissionError, LibraryError) as exc:
        detail = exc.message(context.response_language) if isinstance(exc, LibraryError) else str(exc)
        return {"ok": False, "error": exc.__class__.__name__, "detail": detail}

    return {
        "ok": True,
        "action": action,
        "resource": {
            "id": updated.id,
            "name": updated.name,
            "collection_path": getattr(updated, "collection_path", None),
            "tags": list(getattr(updated, "tags", []) or []),
        },
    }


def _collect_custom_skills_from_context(context: ToolContext) -> list[dict[str, Any]]:
    raw = context.extra.get("custom_skills") if isinstance(context.extra, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("id") or item.get("trigger") or "").strip()
        trigger = str(item.get("trigger") or "").strip()
        title = str(item.get("title") or skill_id or trigger).strip()
        detail = str(item.get("detail") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not (skill_id or trigger):
            continue
        out.append(
            {
                "skill_id": skill_id or trigger.lstrip("$"),
                "kind": "custom",
                "name": title,
                "description": detail,
                "triggers": [trigger] if trigger else [],
                "prompt": prompt,
                "active": True,
                "reviewed": True,
                "source": "custom",
            }
        )
    return out


async def _handle_list_skills(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """List active and available built-in, workspace, and custom skills."""
    from ...skills.runtime import runtime_skill_registry

    kind_filter = str(args.get("kind") or "").strip().lower() or None
    skills_out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    registry = runtime_skill_registry(context.runtime)
    if registry is not None:
        valid_kinds = {"tutor", "knowledge", "action"}
        reg_kind = kind_filter if kind_filter in valid_kinds else None
        if kind_filter != "custom":
            for rec in registry.list_skills(kind=reg_kind, workspace_id=context.workspace_id):
                if rec.quarantined:
                    continue
                seen_ids.add(rec.skill_id)
                front = rec.metadata.get("front_matter") if isinstance(rec.metadata, dict) else {}
                raw_triggers = front.get("triggers") if isinstance(front, dict) else ""
                triggers = [t.strip() for t in str(raw_triggers or "").split(",") if t.strip()]
                skills_out.append(
                    {
                        "skill_id": rec.skill_id,
                        "kind": rec.kind,
                        "name": rec.name,
                        "description": rec.description,
                        "triggers": triggers,
                        "active": rec.active,
                        "reviewed": rec.reviewed,
                        "source": str((rec.metadata or {}).get("origin") or "skill"),
                    }
                )

    if kind_filter in (None, "custom"):
        for item in _collect_custom_skills_from_context(context):
            sid = str(item["skill_id"])
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            skills_out.append(
                {
                    "skill_id": sid,
                    "kind": "custom",
                    "name": item["name"],
                    "description": item["description"],
                    "triggers": item["triggers"],
                    "active": True,
                    "reviewed": True,
                    "source": "custom",
                }
            )

    return {"ok": True, "skills": skills_out, "count": len(skills_out)}


async def _handle_invoke_skill(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Load and invoke one skill by id, $trigger, or title, returning its instructions."""
    from ...skills.runtime import runtime_skill_registry

    query = str(args.get("skill_id") or "").strip()
    task_note = str(args.get("task_note") or "").strip()
    if not query:
        return {"ok": False, "error": "missing_skill_id", "detail": "invoke_skill requires skill_id."}
    needle = query.casefold()
    needle_stripped = needle.lstrip("$")

    registry = runtime_skill_registry(context.runtime)
    if registry is not None:
        matched = None
        for rec in registry.list_skills(workspace_id=context.workspace_id):
            front = rec.metadata.get("front_matter") if isinstance(rec.metadata, dict) else {}
            raw_triggers = front.get("triggers") if isinstance(front, dict) else ""
            triggers = [t.strip().casefold() for t in str(raw_triggers or "").split(",") if t.strip()]
            if (
                rec.skill_id.casefold() == needle
                or rec.skill_id.casefold() == needle_stripped
                or rec.name.casefold() == needle
                or needle in triggers
                or needle_stripped in [t.lstrip("$") for t in triggers]
            ):
                matched = rec
                break
        if matched is not None:
            if matched.quarantined:
                return {
                    "ok": False,
                    "error": "skill_quarantined",
                    "detail": f"Skill {matched.skill_id!r} failed security review and cannot run.",
                }
            body = registry._load_body(matched)
            try:
                registry.record_usage(
                    matched.skill_id,
                    applied=True,
                    workspace_id=context.workspace_id,
                    session_id=context.session_id or "",
                )
            except Exception as exc:
                logger.debug("Skill usage telemetry record skipped: %s", exc)
            return {
                "ok": True,
                "skill_id": matched.skill_id,
                "name": matched.name,
                "kind": matched.kind,
                "instructions": body or matched.description,
                "task_note": task_note or None,
            }

    for item in _collect_custom_skills_from_context(context):
        triggers = [str(t).strip().casefold() for t in item.get("triggers") or []]
        if (
            str(item["skill_id"]).casefold() == needle
            or str(item["skill_id"]).casefold() == needle_stripped
            or str(item["name"]).casefold() == needle
            or needle in triggers
        ):
            return {
                "ok": True,
                "skill_id": item["skill_id"],
                "name": item["name"],
                "kind": "custom",
                "instructions": item.get("prompt") or item.get("description") or item["name"],
                "task_note": task_note or None,
            }

    return {
        "ok": False,
        "error": "skill_not_found",
        "detail": f"No skill matched {query!r}. Call learning_inspect(action='skills') to inspect available skills.",
    }


async def _handle_generate_image(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Generate a visual diagram, illustration, or photorealistic image for the reply."""
    from ..image_generation import generate_pedagogical_image

    return await generate_pedagogical_image(
        context,
        prompt=str(args.get("prompt") or ""),
        title=str(args.get("title") or ""),
        style=str(args.get("style") or "diagram"),
        aspect_ratio=str(args.get("aspect_ratio") or "16:9"),
        save_to_library=args.get("save_to_library", True) is not False,
    )
