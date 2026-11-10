#!/usr/bin/env python3
"""Live web-research probe for the resource-grounding citation contract.

Uses the real controlled search/fetch path (no model key) and projects the
tool result through the same message-part builder the Coach uses. This proves:

- the network path returns fetched sources with real URLs and timestamps;
- the transcript projection is a compact WEB citation (URL + title), never a
  pasted page body;
- a failed/empty search produces no citation.

This is a live-network probe, not a deterministic CI test.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.db.research_repository import ResearchRepository
from app.llm.resource_message_parts import build_resource_display_parts
from app.llm.tools import ToolContext, build_default_tool_registry
from app.research.service import ResearchOrchestratorService

QUERY = "SQLite WAL mode documentation"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        repository = ResearchRepository(Path(tmp) / "research.db")
        research = ResearchOrchestratorService(repository=repository, network_enabled=True)
        runtime = SimpleNamespace(research_service=research)
        context = ToolContext(
            runtime=runtime,
            workspace_id="live-web-grounding",
            session_id="live-web-grounding-session",
            extra={},
        )
        result = build_default_tool_registry().invoke(
            context,
            "search_learning_materials",
            {"query": QUERY, "limit": 3},
        )
        import asyncio

        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        parts = build_resource_display_parts(
            [
                {
                    "type": "tool_result",
                    "name": "search_learning_materials",
                    "ok": True,
                    "result": result,
                }
            ],
            response_language="zh-CN",
        )

    sources = result.get("sources") if isinstance(result, dict) else []
    sources = sources if isinstance(sources, list) else []
    citations = [part for part in parts if part.get("type") == "citation"]
    checks = {
        "toolOk": bool(isinstance(result, dict) and result.get("ok")),
        "fetchedSources": len(sources) > 0,
        "citationCount": len(citations) > 0,
        "allHaveHttpsUrl": all(
            str(part.get("url") or "").startswith("https://") for part in citations
        ),
        "noPastedBody": all(
            "snippet" not in part and "summary" not in part for part in citations
        ),
        "webOrigin": all(
            part.get("referenceOrigin") == "web_research" for part in citations
        ),
        "realFetchedAt": all(bool(source.get("fetched_at")) for source in sources),
    }
    payload = {
        "query": QUERY,
        "ok": all(checks.values()),
        "checks": checks,
        "sources": [
            {
                "title": source.get("title"),
                "url": source.get("url"),
                "source": source.get("source"),
                "fetched_at": source.get("fetched_at"),
                "freshness": source.get("freshness"),
            }
            for source in sources
        ],
        "citations": citations,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
