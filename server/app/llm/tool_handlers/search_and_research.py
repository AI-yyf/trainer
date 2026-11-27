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
import ipaddress
import json
import logging
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from ...core.models import (
    ResourceIndexRequest,
)
from ...resources.capture import CaptureError, capture_source
from .registry_core import (
    ToolContext,
)

logger = logging.getLogger("trainer.llm.tools")


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
    plan = _retrieval_plan(mode, limit)
    visible_hits = [_trim_hit_text(hit, plan["excerpt_budget"]) for hit in visible_hits]
    cache_stats = None
    cache_reader = getattr(resource_service, "search_cache_stats", None)
    if callable(cache_reader):
        try:
            cache_stats = cache_reader()
        except Exception:  # pragma: no cover - defensive
            cache_stats = None
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
        "retrieval_plan": plan,
        **({"cache": cache_stats} if cache_stats else {}),
        "hits": visible_hits[:limit],
    }


def _project_artifact_root(resource_service: Any) -> Any:
    data_root = getattr(resource_service, "data_root", None)
    if data_root is None:
        return None
    return data_root / "project-artifacts"


def _load_project_symbol_payload(resource_service: Any, resource_id: str) -> dict[str, Any] | None:
    """Cached deterministic symbol index for an imported project (P2 artifact)."""

    artifact_root = _project_artifact_root(resource_service)
    if artifact_root is None:
        return None
    artifact_path = artifact_root / f"{resource_id}.symbol-index.json"
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_project_resource(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Pick the imported project: explicit resource_id, else latest kind=code folder."""

    runtime = context.runtime
    resource_service = getattr(runtime, "resource_service", None)
    if resource_service is None:
        return {"ok": False, "error": "service_unavailable", "detail": "The resource library is not attached to this run."}
    repository = getattr(resource_service, "repository", None)
    candidates: list[Any] = []
    if repository is not None:
        try:
            candidates = [
                item
                for item in repository.list_resources(context.workspace_id)
                if str(getattr(item, "kind", "")) == "code"
                and Path(str(getattr(item, "source", "") or "")).is_dir()
            ]
        except Exception:  # pragma: no cover - repository variants
            candidates = []
    candidates.reverse()  # newest first
    requested_id = str(args.get("resource_id") or "").strip()
    requested_name = str(args.get("project") or "").strip().lower()
    resource = None
    if requested_id:
        resource = next((item for item in candidates if str(item.id) == requested_id), None)
        if resource is None:
            return {"ok": False, "error": "project_not_found", "detail": f"No imported project resource {requested_id!r} in this workspace."}
    elif requested_name:
        resource = next((item for item in candidates if requested_name in str(item.name).lower()), None)
        if resource is None:
            return {"ok": False, "error": "project_not_found", "detail": f"No imported project name matching {requested_name!r}."}
    elif candidates:
        resource = candidates[0]
    if resource is None:
        return {
            "ok": False,
            "error": "no_project_imported",
            "detail": (
                "No imported project in this workspace yet. Import one first via "
                "/project/import/github or /project/import/local."
            ),
        }
    payload = _load_project_symbol_payload(resource_service, str(resource.id))
    if payload is None:
        source = str(getattr(resource, "source", "") or "")
        try:
            from ...project.symbols import build_repo_index

            repo_index = build_repo_index(Path(source))
            payload = repo_index.to_payload()
        except (OSError, ValueError, RuntimeError):
            return {"ok": False, "error": "artifact_missing", "detail": "Symbol index is unavailable and the repo source cannot be re-analyzed."}
    return {"ok": True, "resource": resource, "payload": payload}


async def _handle_list_project_modules(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """项目问答: module map of the imported project (deterministic artifact)."""

    resolved = _resolve_project_resource(context, args)
    if not resolved.get("ok"):
        return resolved
    resource = resolved["resource"]
    payload = resolved["payload"]
    files: list[str] = [str(f) for f in payload.get("files", [])]
    symbols: list[dict[str, Any]] = payload.get("symbols", []) or []

    module_names = sorted({f.split("/", 1)[0] if "/" in f else "." for f in files})
    modules = []
    for module in module_names:
        module_files = [f for f in files if (f.split("/", 1)[0] if "/" in f else ".") == module]
        module_symbol_count = sum(1 for s in symbols if (str(s.get("path", "")).split("/", 1)[0] if "/" in str(s.get("path", "")) else ".") == module)
        languages = sorted({str(Path(f).suffix).lower() for f in module_files if Path(f).suffix})
        modules.append(
            {
                "module": module,
                "file_count": len(module_files),
                "symbol_count": module_symbol_count,
                "languages": languages,
                "top_files": module_files[:8],
            }
        )
    return {
        "ok": True,
        "project": str(getattr(resource, "name", "") or ""),
        "resource_id": str(resource.id),
        "commit_sha": str(payload.get("commit_sha") or "") or None,
        "file_count": int(payload.get("file_count") or len(files)),
        "symbol_count": int(payload.get("symbol_count") or len(symbols)),
        "modules": modules[:20],
        "summary": (
            f"Project {getattr(resource, 'name', '')}: {payload.get('file_count')} files, "
            f"{payload.get('symbol_count')} symbols across {len(modules)} top-level modules."
        ),
    }


async def _handle_read_project_symbol(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """项目问答: locate one symbol in the imported repo and return its source excerpt."""

    name = str(args.get("name") or args.get("symbol") or "").strip()
    if not name:
        return {"ok": False, "error": "missing_name", "detail": "read_project_symbol requires the symbol name."}
    file_hint = str(args.get("file") or "").strip().lower()
    resolved = _resolve_project_resource(context, args)
    if not resolved.get("ok"):
        return resolved
    resource = resolved["resource"]
    payload = resolved["payload"]
    symbols = [s for s in (payload.get("symbols", []) or []) if isinstance(s, dict)]

    matches = [s for s in symbols if str(s.get("name", "")) == name]
    if not matches:
        matches = [s for s in symbols if str(s.get("name", "")).startswith(name)]
    if file_hint:
        matches = [s for s in matches if file_hint in str(s.get("path", "")).lower()]
    if not matches:
        close = sorted(
            {
                str(s.get("name", ""))
                for s in symbols
                if name.lower() in str(s.get("name", "")).lower()
            }
        )[:5]
        return {
            "ok": False,
            "error": "symbol_not_found",
            "detail": f"Symbol {name!r} not found in {getattr(resource, 'name', 'project')}.",
            "suggestions": close,
        }

    match = matches[0]
    source = Path(str(getattr(resource, "source", "") or ""))
    symbol_path = source / str(match.get("path", ""))
    line = int(match.get("line", 1) or 1)
    excerpt = ""
    try:
        text = symbol_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(0, line - 9)
        end = min(len(lines), line + 31)
        excerpt = "\n".join(lines[start:end])[:2000]
    except OSError:
        excerpt = ""
    return {
        "ok": True,
        "symbol": str(match.get("name", name)),
        "kind": str(match.get("kind", "")),
        "path": str(match.get("path", "")),
        "line": line,
        "excerpt": excerpt or None,
        "excerpt_available": bool(excerpt),
        "commit_sha": str(payload.get("commit_sha") or "") or None,
        "resource_id": str(resource.id),
        "additional_matches": [
            {"path": s.get("path"), "line": s.get("line"), "kind": s.get("kind")}
            for s in matches[1:4]
        ],
    }


async def _handle_analyze_project_impact(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """项目问答: 改动影响面 — changed symbols → affected callers (deterministic)."""

    resolved = _resolve_project_resource(context, args)
    if not resolved.get("ok"):
        return resolved
    resource = resolved["resource"]
    source = Path(str(getattr(resource, "source", "") or ""))
    if not source.is_dir():
        return {"ok": False, "error": "repo_missing", "detail": f"Project directory is missing: {source}"}
    since = str(args.get("since") or "").strip()
    depth_raw = args.get("depth", 2)
    try:
        depth = max(1, min(int(depth_raw), 3))
    except Exception:
        depth = 2
    try:
        from ...project.callgraph import build_call_graph, compute_change_impact
        from ...project.symbols import build_repo_index

        repo_index = build_repo_index(source)
        graph = build_call_graph(source, repo_index)
        impact = compute_change_impact(source, repo_index, graph, since=since, depth=depth)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"ok": False, "error": "impact_failed", "detail": str(exc)}
    payload = impact.to_payload()
    return {
        "ok": True,
        "project": str(getattr(resource, "name", "") or ""),
        "resource_id": str(resource.id),
        "callgraph": graph.to_payload(limit=40),
        **payload,
    }


MAX_RESEARCH_SEARCH_ROUNDS = 24


MAX_RESEARCH_SOURCES = 48


ADAPTIVE_EVIDENCE_DIMENSIONS = frozenset(
    {"coverage", "source_quality", "recency", "contradictions", "applicability"}
)


def _normalized_research_facets(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    facets: list[str] = []
    for raw in value:
        facet = " ".join(str(raw or "").split()).strip()
        if not facet or len(facet) > 96 or facet.casefold() in {item.casefold() for item in facets}:
            continue
        facets.append(facet)
        if len(facets) >= 8:
            break
    return facets


def _normalized_research_domains(value: object, query: str) -> list[str]:
    raw_domains = value if isinstance(value, list) else []
    raw_domains = [*raw_domains, *re.findall(r"\bsite:([^\s]+)", query, flags=re.IGNORECASE)]
    domains: list[str] = []
    for raw in raw_domains:
        domain = str(raw or "").strip().lower().strip("./").removeprefix("www.")
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:8]


def _source_matches_preferred_domain(source: dict[str, Any], domains: list[str]) -> bool:
    if not domains:
        return False
    domain = urlsplit(str(source.get("url") or "")).netloc.lower().removeprefix("www.")
    return any(domain == preferred or domain.endswith("." + preferred) for preferred in domains)


def _source_trust_score(source: dict[str, Any]) -> float:
    try:
        return float(source.get("trust_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _transition_formal_research_to_synthesis(context: ToolContext) -> None:
    context.extra["_formal_research_synthesizing"] = True
    denied_raw = context.extra.get("denied_tool_names")
    denied = (
        [str(name).strip() for name in denied_raw if str(name).strip()]
        if isinstance(denied_raw, (list, tuple, set))
        else []
    )
    context.extra["denied_tool_names"] = list(
        dict.fromkeys(
            [
                *denied,
                "web_fetch",
                "library_read",
                "search_learning_materials",
                "assess_research_evidence",
                "search_resources",
            ]
        )
    )
    existing_allowed_raw = context.extra.get("allowed_tool_names")
    synthesis_candidates = ["learning_action", "save_formal_plan"]
    if isinstance(existing_allowed_raw, (list, tuple, set)):
        existing_allowed = {
            str(name).strip() for name in existing_allowed_raw if str(name).strip()
        }
        filtered = [name for name in synthesis_candidates if name in existing_allowed]
        synthesis_tools = filtered or ["learning_action"]
    else:
        synthesis_tools = ["learning_action"]
    context.extra["allowed_tool_names"] = synthesis_tools


async def _handle_search_learning_materials(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {
            "ok": False,
            "error": "missing_query",
            "detail": "search_learning_materials requires a non-empty query.",
        }
    try:
        limit = max(1, min(int(args.get("limit", 4)), 6))
    except (TypeError, ValueError):
        limit = 4
    formal_plan_research = context.extra.get("formal_plan_mutation") is True
    state_key = "_learning_material_research_state"
    state_raw = context.extra.get(state_key)
    state = dict(state_raw) if isinstance(state_raw, dict) else {}
    prior_search_count = int(state.get("search_count") or 0)
    if prior_search_count >= MAX_RESEARCH_SEARCH_ROUNDS:
        return {
            "ok": False,
            "error": "research_search_safety_limit_reached",
            "detail": (
                "The emergency search-loop limit was reached. Assess the accumulated evidence "
                "as sufficient or exhausted_with_gaps; do not start another broad search."
            ),
            "research_status": str(state.get("status") or "gaps_remain"),
            "search_count": prior_search_count,
            "safety_search_limit": MAX_RESEARCH_SEARCH_ROUNDS,
        }
    required_facets = _normalized_research_facets(state.get("required_facets"))
    requested_facets = _normalized_research_facets(args.get("required_facets"))
    if formal_plan_research and not required_facets and len(requested_facets) < 2:
        return {
            "ok": False,
            "error": "research_facets_required",
            "detail": (
                "A source-grounded formal plan needs 2-8 explicit required_facets before search. "
                "List the distinct concepts or decisions the final plan must substantiate."
            ),
            "query": query,
            "sources": [],
        }
    if not required_facets:
        required_facets = requested_facets
    raw_requested_domains = args.get("preferred_domains")
    requested_domains = (
        list(raw_requested_domains) if isinstance(raw_requested_domains, list) else []
    )
    raw_prior_domains = state.get("preferred_domains")
    prior_domains = list(raw_prior_domains) if isinstance(raw_prior_domains, list) else []
    preferred_domains = _normalized_research_domains(
        [*prior_domains, *requested_domains],
        query,
    )
    search_query = query
    if requested_domains and not re.search(r"\bsite:", query, flags=re.IGNORECASE):
        search_query = " ".join(
            [*(f"site:{domain}" for domain in preferred_domains[:2]), query]
        )
    prior_sources_raw = state.get("sources")
    prior_sources = (
        [item for item in prior_sources_raw if isinstance(item, dict)]
        if isinstance(prior_sources_raw, list)
        else []
    )
    research_service = getattr(context.runtime, "research_service", None)
    if research_service is None or not hasattr(research_service, "search_web"):
        return {
            "ok": False,
            "error": "service_unavailable",
            "detail": "Verified public learning-material search is unavailable in this runtime.",
        }
    focus_area = str(args.get("focus_area") or "Learning materials").strip()
    try:
        result = research_service.search_web(
            search_query,
            workspace_id=context.workspace_id,
            focus_area=focus_area,
            limit=limit,
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # pragma: no cover - integration guard
        return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
    if not isinstance(result, dict):
        return {
            "ok": False,
            "error": "invalid_search_result",
            "detail": "Learning-material search returned an unreadable result.",
        }
    if result.get("error"):
        return {
            "ok": False,
            "error": str(result.get("reason_code") or "search_failed"),
            "detail": str(result.get("error")),
            "query": query,
            "sources": [],
        }
    sources: list[dict[str, Any]] = []
    raw_results = result.get("results")
    for item in raw_results if isinstance(raw_results, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        fetched_at = str(item.get("fetched_at") or "").strip()
        if not url or not title or not fetched_at:
            continue
        sources.append(
            {
                "id": str(item.get("id") or "").strip(),
                "title": title,
                "url": url,
                "source": str(item.get("source") or "").strip(),
                "snippet": str(item.get("snippet") or "").strip()[:240],
                "evidence_excerpt": str(item.get("evidence_excerpt") or "").strip()[:1200],
                "fetched_at": fetched_at,
                "freshness": str(item.get("freshness") or "fresh").strip(),
                "trust_score": item.get("trust_score"),
            }
        )
    if not sources:
        return {
            "ok": False,
            "error": "no_verified_sources",
            "detail": "No public result page could be fetched with provenance.",
            "query": query,
            "sources": [],
        }
    merged_sources: dict[str, dict[str, Any]] = {}
    for source in [*prior_sources, *sources]:
        source_url = str(source.get("url") or "").strip()
        if source_url and source_url not in merged_sources:
            # Keep the first fetched record so its evidence ID remains stable across targeted
            # follow-up searches. The model may legitimately cite that ID in a later assessment.
            merged_sources[source_url] = source
    accumulated_sources = list(merged_sources.values())[:MAX_RESEARCH_SOURCES]
    authoritative_sources = [
        source
        for source in accumulated_sources
        if _source_matches_preferred_domain(source, preferred_domains)
        or _source_trust_score(source) >= 0.8
    ]
    previous_urls = {
        str(source.get("url") or "").strip()
        for source in prior_sources
        if str(source.get("url") or "").strip()
    }
    new_source_count = sum(
        str(source.get("url") or "").strip() not in previous_urls
        for source in accumulated_sources
    )
    search_count = int(state.get("search_count") or 0) + 1
    state = {
        "required_facets": required_facets,
        "preferred_domains": preferred_domains,
        "sources": accumulated_sources,
        "search_count": search_count,
        "status": "awaiting_model_assessment",
    }
    prior_assessment = [
        item for item in state_raw.get("assessment", []) if isinstance(item, dict)
    ] if isinstance(state_raw, dict) else []
    raw_covered_facets = (
        state_raw.get("covered_facets") if isinstance(state_raw, dict) else None
    )
    covered_facets_list: list[Any] = (
        list(raw_covered_facets) if isinstance(raw_covered_facets, list) else []
    )
    prior_covered_facets = _normalized_research_facets(covered_facets_list)
    raw_evidence_standard = (
        state_raw.get("evidence_standard") if isinstance(state_raw, dict) else None
    )
    prior_evidence_standard = (
        dict(raw_evidence_standard) if isinstance(raw_evidence_standard, dict) else {}
    )
    if prior_assessment:
        state["assessment"] = prior_assessment
    if prior_covered_facets:
        state["covered_facets"] = prior_covered_facets
    if prior_evidence_standard:
        state["evidence_standard"] = prior_evidence_standard
    if formal_plan_research:
        existing_allowed = context.extra.get("allowed_tool_names")
        if isinstance(existing_allowed, (list, tuple, set)):
            saved_allowed = [
                str(name).strip() for name in existing_allowed if str(name).strip()
            ]
            state["had_allowed_tool_names"] = True
            state["allowed_tool_names_before_assessment"] = saved_allowed
            if "assess_research_evidence" in saved_allowed and "web_fetch" not in saved_allowed:
                context.extra["allowed_tool_names"] = ["assess_research_evidence"]
            else:
                context.extra["allowed_tool_names"] = ["web_fetch"]
        else:
            state["had_allowed_tool_names"] = False
            state["allowed_tool_names_before_assessment"] = []
            context.extra["allowed_tool_names"] = ["web_fetch", "assess_research_evidence"]
    context.extra[state_key] = state
    return {
        "ok": True,
        "query": str(result.get("query") or search_query),
        "source_count": len(accumulated_sources),
        "citation_required": True,
        "research_complete": False,
        "research_exhausted": False,
        "research_status": state["status"],
        "evidence_coverage": {
            "required_facets": required_facets,
            "authoritative_source_count": len(authoritative_sources),
            "new_source_count": new_source_count,
            "search_count": search_count,
            "safety_searches_remaining": max(0, MAX_RESEARCH_SEARCH_ROUNDS - search_count),
        },
        "sources": accumulated_sources,
        "instruction": (
            "Read the fetched excerpts and call web_fetch(action='assess_evidence', ...). You—not a keyword "
            "counter—must judge every required facet, cite supporting source IDs, and explain "
            "your reasoning. Do not search again until the assessment returns gaps_remain."
        ),
    }


async def _handle_assess_research_evidence(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    state_raw = context.extra.get("_learning_material_research_state")
    state = dict(state_raw) if isinstance(state_raw, dict) else {}
    required_facets = _normalized_research_facets(state.get("required_facets"))
    sources = [item for item in state.get("sources", []) if isinstance(item, dict)]
    if not required_facets or not sources:
        return {
            "ok": False,
            "error": "research_evidence_missing",
            "detail": "Search for verified evidence before assessing its sufficiency.",
        }

    verdict = str(args.get("verdict") or "").strip()
    if verdict not in {"sufficient", "gaps_remain", "exhausted_with_gaps"}:
        return {
            "ok": False,
            "error": "invalid_research_verdict",
            "detail": "verdict must be sufficient, gaps_remain, or exhausted_with_gaps.",
        }
    raw_standard = args.get("evidence_standard")
    evidence_standard = dict(raw_standard) if isinstance(raw_standard, dict) else {}
    risk_level = str(evidence_standard.get("risk_level") or "").strip()
    stopping_rule = " ".join(str(evidence_standard.get("stopping_rule") or "").split())
    try:
        raw_min_sources = evidence_standard.get("minimum_independent_sources")
        minimum_independent_sources = (
            int(raw_min_sources) if isinstance(raw_min_sources, (int, float)) else 0
        )
    except (TypeError, ValueError):
        minimum_independent_sources = 0
    requires_authoritative_source = evidence_standard.get("requires_authoritative_source")
    claim_types = [
        " ".join(str(item or "").split())
        for item in evidence_standard.get("claim_types", [])
        if str(item or "").strip()
    ] if isinstance(evidence_standard.get("claim_types"), list) else []
    freshness_requirement = str(
        evidence_standard.get("freshness_requirement") or ""
    ).strip()
    applicability_scope = " ".join(
        str(evidence_standard.get("applicability_scope") or "").split()
    )
    unresolved_uncertainties = [
        " ".join(str(item or "").split())
        for item in evidence_standard.get("unresolved_uncertainties", [])
        if str(item or "").strip()
    ] if isinstance(evidence_standard.get("unresolved_uncertainties"), list) else []
    raw_quality_checks = evidence_standard.get("quality_checks")
    quality_checks = [
        item for item in raw_quality_checks if isinstance(item, dict)
    ] if isinstance(raw_quality_checks, list) else []
    available_source_ids = {
        str(identifier or "").strip()
        for source in sources
        for identifier in (source.get("id"), source.get("url"))
        if str(identifier or "").strip()
    }
    standard_errors: list[str] = []
    if risk_level not in {"exploratory", "normal", "high_stakes"}:
        standard_errors.append(
            "evidence_standard.risk_level must be exploratory, normal, or high_stakes"
        )
    if minimum_independent_sources < 1 or minimum_independent_sources > 8:
        standard_errors.append(
            "evidence_standard.minimum_independent_sources must be between 1 and 8"
        )
    if not isinstance(requires_authoritative_source, bool):
        standard_errors.append(
            "evidence_standard.requires_authoritative_source must be boolean"
        )
    if not claim_types or len(claim_types) > 6:
        standard_errors.append("evidence_standard.claim_types must contain 1-6 claim types")
    if freshness_requirement not in {"historical", "stable", "current", "latest"}:
        standard_errors.append(
            "evidence_standard.freshness_requirement must be historical, stable, current, or latest"
        )
    if len(applicability_scope) < 16:
        standard_errors.append(
            "evidence_standard.applicability_scope must state the scope and boundary"
        )
    if len(stopping_rule) < 20:
        standard_errors.append(
            "evidence_standard.stopping_rule must explain the task-adapted stop rule"
        )
    if len(unresolved_uncertainties) > 8:
        standard_errors.append(
            "evidence_standard.unresolved_uncertainties accepts at most 8 items"
        )
    checks_by_dimension: dict[str, dict[str, Any]] = {}
    normalized_quality_checks: list[dict[str, Any]] = []
    for check in quality_checks:
        dimension = str(check.get("dimension") or "").strip()
        if dimension in checks_by_dimension:
            standard_errors.append(f"duplicate evidence quality dimension: {dimension}")
            continue
        status = str(check.get("status") or "").strip()
        rationale = " ".join(str(check.get("rationale") or "").split())
        source_ids = list(
            dict.fromkeys(
                str(item or "").strip()
                for item in check.get("source_ids", [])
                if str(item or "").strip()
            )
        ) if isinstance(check.get("source_ids"), list) else []
        if dimension not in ADAPTIVE_EVIDENCE_DIMENSIONS:
            standard_errors.append(f"unknown evidence quality dimension: {dimension}")
            continue
        if status not in {"satisfied", "unresolved", "not_applicable"}:
            standard_errors.append(f"{dimension}: invalid quality-check status")
        if len(rationale) < 16:
            standard_errors.append(f"{dimension}: quality-check rationale is too short")
        unknown_source_ids = [
            identifier for identifier in source_ids if identifier not in available_source_ids
        ]
        if unknown_source_ids:
            standard_errors.append(
                f"{dimension}: quality check cites unknown source IDs {unknown_source_ids}"
            )
        if status == "satisfied" and not source_ids:
            standard_errors.append(
                f"{dimension}: a satisfied quality check requires supporting source IDs"
            )
        normalized_check = {
            "dimension": dimension,
            "status": status,
            "source_ids": source_ids,
            "rationale": rationale,
        }
        checks_by_dimension[dimension] = normalized_check
        normalized_quality_checks.append(normalized_check)
    missing_dimensions = sorted(ADAPTIVE_EVIDENCE_DIMENSIONS - checks_by_dimension.keys())
    if missing_dimensions:
        standard_errors.append(
            "evidence_standard.quality_checks is missing dimensions " + str(missing_dimensions)
        )
    if standard_errors:
        return {
            "ok": False,
            "error": "invalid_adaptive_evidence_standard",
            "detail": (
                "The model must declare a task-adapted evidence standard before judging "
                "sufficiency."
            ),
            "integrity_errors": standard_errors,
        }
    normalized_standard = {
        "risk_level": risk_level,
        "minimum_independent_sources": minimum_independent_sources,
        "requires_authoritative_source": requires_authoritative_source,
        "claim_types": claim_types,
        "freshness_requirement": freshness_requirement,
        "applicability_scope": applicability_scope,
        "stopping_rule": stopping_rule,
        "unresolved_uncertainties": unresolved_uncertainties,
        "quality_checks": normalized_quality_checks,
    }
    raw_assessments = args.get("facet_assessments")
    assessments = (
        [item for item in raw_assessments if isinstance(item, dict)]
        if isinstance(raw_assessments, list)
        else []
    )
    by_facet = {
        " ".join(str(item.get("facet") or "").casefold().split()): item
        for item in assessments
        if str(item.get("facet") or "").strip()
    }
    missing_assessments = [
        facet for facet in required_facets if facet.casefold() not in by_facet
    ]
    if missing_assessments:
        return {
            "ok": False,
            "error": "incomplete_evidence_assessment",
            "detail": "Every required facet needs one explicit model judgment.",
            "missing_facets": missing_assessments,
        }

    source_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        for identifier in (source.get("id"), source.get("url")):
            normalized = str(identifier or "").strip()
            if normalized:
                source_by_id[normalized] = source
    normalized_assessments: list[dict[str, Any]] = []
    cited_ids: set[str] = set()
    integrity_errors: list[str] = []
    for facet in required_facets:
        assessment = by_facet[facet.casefold()]
        status = str(assessment.get("status") or "").strip()
        rationale = " ".join(str(assessment.get("rationale") or "").split())
        raw_ids = assessment.get("source_ids")
        source_ids = list(
            dict.fromkeys(
                str(identifier or "").strip()
                for identifier in (raw_ids if isinstance(raw_ids, list) else [])
                if str(identifier or "").strip()
            )
        )
        raw_quotes = assessment.get("evidence_quotes")
        evidence_quotes = (
            [item for item in raw_quotes if isinstance(item, dict)]
            if isinstance(raw_quotes, list)
            else []
        )
        unknown_ids = [identifier for identifier in source_ids if identifier not in source_by_id]
        if status not in {"covered", "missing"}:
            integrity_errors.append(f"{facet}: status must be covered or missing")
        if len(rationale) < 12:
            integrity_errors.append(f"{facet}: rationale is too short to audit")
        if unknown_ids:
            integrity_errors.append(f"{facet}: unknown source IDs {unknown_ids}")
        if status == "covered" and not source_ids:
            integrity_errors.append(f"{facet}: covered judgments require source IDs")
        if status == "covered" and not evidence_quotes:
            integrity_errors.append(f"{facet}: covered judgments require evidence quotes")
        normalized_quotes: list[dict[str, str]] = []
        for quote_item in evidence_quotes:
            quote_source_id = str(quote_item.get("source_id") or "").strip()
            quote = " ".join(str(quote_item.get("quote") or "").split())
            if quote_source_id not in source_by_id or quote_source_id not in source_ids:
                integrity_errors.append(
                    f"{facet}: quote source {quote_source_id!r} is not a cited fetched source"
                )
                continue
            if len(quote) < 8 or len(quote) > 280:
                integrity_errors.append(f"{facet}: evidence quote length is not auditable")
                continue
            source = source_by_id[quote_source_id]
            source_text = " ".join(
                str(source.get(key) or "")
                for key in ("title", "snippet", "evidence_excerpt")
            )
            normalized_source_text = " ".join(source_text.casefold().split())
            if quote.casefold() not in normalized_source_text:
                integrity_errors.append(
                    f"{facet}: evidence quote is not present in source {quote_source_id}"
                )
                continue
            normalized_quotes.append({"source_id": quote_source_id, "quote": quote})
        cited_ids.update(identifier for identifier in source_ids if identifier in source_by_id)
        normalized_assessments.append(
            {
                "facet": facet,
                "status": status,
                "source_ids": source_ids,
                "evidence_quotes": normalized_quotes,
                "rationale": rationale,
            }
        )
    if integrity_errors:
        return {
            "ok": False,
            "error": "invalid_evidence_assessment",
            "detail": "The model assessment failed provenance checks.",
            "integrity_errors": integrity_errors,
        }

    covered_facets = [
        item["facet"] for item in normalized_assessments if item["status"] == "covered"
    ]
    missing_facets = [
        item["facet"] for item in normalized_assessments if item["status"] == "missing"
    ]
    coverage_check = next(
        (
            check
            for check in normalized_quality_checks
            if check.get("dimension") == "coverage"
        ),
        None,
    )
    if missing_facets and (
        not isinstance(coverage_check, dict)
        or coverage_check.get("status") != "unresolved"
    ):
        return {
            "ok": False,
            "error": "inconsistent_adaptive_evidence_standard",
            "detail": (
                "Missing facets require the adaptive coverage quality check to remain unresolved."
            ),
            "missing_facets": missing_facets,
            "evidence_standard": normalized_standard,
        }
    preferred_domains = [
        str(domain) for domain in state.get("preferred_domains", []) if str(domain).strip()
    ]
    authoritative_ids = {
        identifier
        for identifier in cited_ids
        if _source_matches_preferred_domain(source_by_id[identifier], preferred_domains)
        or _source_trust_score(source_by_id[identifier]) >= 0.8
    }
    if verdict == "sufficient" and (
        missing_facets
        or len(cited_ids) < minimum_independent_sources
        or (requires_authoritative_source and not authoritative_ids)
        or unresolved_uncertainties
        or any(check["status"] == "unresolved" for check in normalized_quality_checks)
    ):
        return {
            "ok": False,
            "error": "unsupported_sufficient_verdict",
            "detail": (
                "The sufficient verdict does not satisfy the model's declared adaptive evidence "
                "standard or still contains unresolved uncertainties."
            ),
            "missing_facets": missing_facets,
            "evidence_standard": normalized_standard,
            "cited_source_count": len(cited_ids),
            "authoritative_cited_source_count": len(authoritative_ids),
        }
    if verdict != "sufficient" and not missing_facets:
        return {
            "ok": False,
            "error": "gap_verdict_without_gap",
            "detail": "A gap verdict must identify at least one missing facet.",
        }
    search_count = int(state.get("search_count") or 0)
    if verdict == "gaps_remain" and search_count >= MAX_RESEARCH_SEARCH_ROUNDS:
        return {
            "ok": False,
            "error": "research_search_safety_limit_reached",
            "detail": (
                "The emergency loop limit is reached. The model must now choose sufficient or "
                "exhausted_with_gaps from the accumulated evidence."
            ),
            "missing_facets": missing_facets,
            "search_count": search_count,
            "safety_search_limit": MAX_RESEARCH_SEARCH_ROUNDS,
        }

    state["status"] = verdict
    state["assessment"] = normalized_assessments
    state["covered_facets"] = covered_facets
    state["evidence_standard"] = normalized_standard
    context.extra["_learning_material_research_state"] = state
    if state.get("had_allowed_tool_names") is True:
        context.extra["allowed_tool_names"] = list(
            state.get("allowed_tool_names_before_assessment") or []
        )
    else:
        context.extra.pop("allowed_tool_names", None)
    if verdict in {"sufficient", "exhausted_with_gaps"}:
        _transition_formal_research_to_synthesis(context)
    return {
        "ok": True,
        "research_status": verdict,
        "research_complete": verdict == "sufficient",
        "research_exhausted": verdict == "exhausted_with_gaps",
        "evidence_coverage": {
            "required_facets": required_facets,
            "covered_facets": covered_facets,
            "missing_facets": missing_facets,
            "coverage_ratio": round(len(covered_facets) / len(required_facets), 3),
            "cited_source_count": len(cited_ids),
            "authoritative_cited_source_count": len(authoritative_ids),
            "evidence_standard": normalized_standard,
            "model_assessments": normalized_assessments,
            "search_count": search_count,
            "safety_searches_remaining": max(0, MAX_RESEARCH_SEARCH_ROUNDS - search_count),
        },
        "instruction": (
            "The model judged the evidence sufficient. Stop searching and call learning_action(action='save_formal_plan', ...)."
            if verdict == "sufficient"
            else "Search only for the model-identified missing facets, then assess again."
            if verdict == "gaps_remain"
            else "The model judged further search unproductive. Save a plan via learning_action(action='save_formal_plan', ...) that explicitly marks the gaps."
        ),
    }


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


def _capture_kind_for_url(url: str) -> str:
    """Pick the controlled-capture lane before the fetch starts."""

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in {"github.com", "www.github.com"}:
        return "github_repo"
    if parsed.path.lower().endswith(".pdf"):
        return "pdf"
    return "web"


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
    tags = (
        [str(tag).strip() for tag in raw_tags if str(tag).strip()][:20]
        if isinstance(raw_tags, list)
        else []
    )
    capture_kind = _capture_kind_for_url(url)
    try:
        captured = capture_source(
            capture_kind,
            url,
            network_enabled=True,
            declared_title=str(args.get("name") or "").strip() or None,
        )
    except CaptureError as exc:
        return {
            "ok": False,
            "error": "resource_capture_failed",
            "detail": exc.detail,
            "source": {"requested_url": url, "capture_kind": capture_kind},
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "resource_capture_failed",
            "detail": str(exc),
            "source": {"requested_url": url, "capture_kind": capture_kind},
        }

    # The controlled capture pipeline reads the source and leaves a real
    # Markdown (or PDF) snapshot in the library; a URL-only record would not be
    # openable or teachable after the page changes.
    request = captured.as_upload_request(
        session_id=context.session_id,
        workspace_id=context.workspace_id,
    )
    request = request.model_copy(
        update={"tags": list(dict.fromkeys([*request.tags, *tags]))}
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
            "source": {"requested_url": url, "capture_kind": capture_kind},
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
            "requested_url": url,
            "canonical_url": captured.source_url or url,
            "fetched_at": payload.get("fetched_at") or captured.captured_at,
            "capture_kind": captured.kind,
            "content_format": "markdown" if captured.upload_kind == "markdown" else captured.upload_kind,
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
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("Search payload model_dump fallback: %s", exc)
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return asdict(cast(Any, value))
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("Search payload asdict fallback: %s", exc)
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
            raw_location = entry.get("location")
            location: dict[str, Any] = dict(raw_location) if isinstance(raw_location, dict) else {}
            anchor_id = (
                entry.get("anchor_id")
                or entry.get("anchorId")
                or location.get("anchor_id")
                or location.get("paragraph_anchor")
                or location.get("chunk_id")
            )
            line_start = entry.get("line_start") or entry.get("lineStart") or location.get("line_start")
            line_end = entry.get("line_end") or entry.get("lineEnd") or location.get("line_end")
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
                    "version_id": entry.get("version_id") or entry.get("versionId") or "",
                    "content_hash": entry.get("content_hash") or entry.get("contentHash") or "",
                    "stale": bool(entry.get("stale")),
                    "current_version_id": (
                        entry.get("current_version_id") or entry.get("currentVersionId") or ""
                    ),
                    "current_content_hash": (
                        entry.get("current_content_hash") or entry.get("currentContentHash") or ""
                    ),
                    "location": location,
                    "anchor_id": anchor_id,
                    "line_start": line_start,
                    "line_end": line_end,
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


_RETRIEVAL_EXCERPT_BUDGETS = {"broad": 180, "narrow": 300, "verify": 420}


_HIT_TEXT_FIELDS = ("excerpt", "summary", "snippet", "text")


def _retrieval_plan(mode: str, limit: int) -> dict[str, Any]:
    """分层检索预算: metadata hit → bounded excerpt → anchor read on demand."""

    return {
        "mode": mode,
        "visible_limit": limit,
        "excerpt_budget": _RETRIEVAL_EXCERPT_BUDGETS.get(mode, 300),
        "read_more": "read_resource_excerpt(anchor_id) for the exact passage",
    }


def _trim_hit_text(hit: dict[str, Any], budget: int) -> dict[str, Any]:
    trimmed = dict(hit)
    truncated = False
    for name in _HIT_TEXT_FIELDS:
        value = trimmed.get(name)
        if isinstance(value, str) and len(value) > budget:
            trimmed[name] = value[:budget].rstrip() + "…"
            truncated = True
    if truncated:
        trimmed["truncated"] = True
    return trimmed


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
