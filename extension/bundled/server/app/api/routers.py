"""Sidecar FastAPI router assembly.

Composes cohesive domain services from ``router_domains`` and mounts ``core``
ahead of the domain sub-routers so overlapping paths keep their historical
match precedence.
"""

from __future__ import annotations

from fastapi import APIRouter

from ._singleflight import (
    claim_session_request_singleflight as claim_session_request_singleflight,
)
from ._singleflight import (
    fail_session_request_singleflight as fail_session_request_singleflight,
)
from ._singleflight import (
    publish_session_request_singleflight as publish_session_request_singleflight,
)
from .router_domains import (
    RouterDomainContext,
    build_coach_support_deps,
    build_router_deps,
)
from .router_support import (
    _attach_requested_workspace_files as _attach_requested_workspace_files,
)
from .router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from .router_support import (
    _resolve_agent_loop_enabled as _resolve_agent_loop_enabled,
)
from .router_support import (
    overlay_session_response_honesty_stamps as overlay_session_response_honesty_stamps,
)
from .router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .routes.browser import build_browser_router
from .routes.browser_chat import build_browser_chat_router
from .routes.core import CoreRouteDeps, build_core_router
from .routes.goal import build_goal_router
from .routes.learning import build_learning_router
from .routes.mcp import build_mcp_router
from .routes.memory import build_memory_router
from .routes.plan import build_plan_router
from .routes.project import build_project_router
from .routes.provider import build_provider_router
from .routes.resources import build_resources_router
from .routes.sandbox import build_sandbox_router
from .routes.workspace import build_workspace_router
from .runtime import TrainerRuntime

__all__ = [
    "_attach_requested_workspace_files",
    "_request_is_plan_agent_turn",
    "_resolve_agent_loop_enabled",
    "build_router",
    "claim_session_request_singleflight",
    "fail_session_request_singleflight",
    "overlay_session_response_honesty_stamps",
    "publish_session_request_singleflight",
    "reset_provider_scheme_cache",
]


def build_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter()
    domain = RouterDomainContext(runtime)
    coach_support_deps = build_coach_support_deps(domain)
    deps = build_router_deps(domain)
    core_route_deps = CoreRouteDeps(
        domain=domain,
        coach_support_deps=coach_support_deps,
    )

    resources_router, prepare_research_turn = build_resources_router(runtime, deps)
    router.include_router(
        build_core_router(runtime, deps, core_route_deps, prepare_research_turn)
    )
    router.include_router(build_workspace_router(runtime, deps))
    router.include_router(build_project_router(runtime, deps))
    router.include_router(build_memory_router(runtime, deps))
    router.include_router(build_learning_router(runtime, deps))
    router.include_router(build_goal_router(runtime, deps))
    router.include_router(resources_router)
    router.include_router(build_browser_router(runtime, deps))
    router.include_router(build_browser_chat_router(runtime, deps))
    router.include_router(build_provider_router(runtime, deps))
    router.include_router(build_sandbox_router(runtime, deps))
    router.include_router(build_plan_router(runtime, deps))
    router.include_router(build_mcp_router(runtime, deps))
    return router
