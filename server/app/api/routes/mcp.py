from __future__ import annotations

from fastapi import APIRouter

from ...llm.mcp_client import probe_mcp_servers
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_mcp_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    """Settings-visible MCP server status.

    Surfaces the configured server count, discovered tool count, and an
    honest ``unavailable`` state (with diagnostic + 中文 message) for servers
    whose process cannot start — never silent.
    """
    _ = deps
    router = APIRouter(tags=["mcp"])

    @router.get("/mcp/status", response_model=None)
    async def mcp_status() -> dict[str, object]:
        return await probe_mcp_servers(runtime)

    return router
