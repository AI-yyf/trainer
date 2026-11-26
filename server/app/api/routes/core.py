"""Core sidecar route orchestrator.

Registered before the domain routers so overlapping paths keep their
historical match order:
1. Session, snapshot, health, checkpoints, turn, cancel, steer (``core_sessions``)
2. SSE streaming pipelines (``core_streaming``)
3. Task, evaluation, learning signals, plan candidates (``core_evaluation``)
4. Training cards, streaming card generation, drills, lab/review actions (``core_training``)
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from ..coach_support import CoachSupportDeps
from ..router_domains import RouterDomainContext
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from ..routes._deps import RouterDeps
from ..routes.resources import PrepareResearchTurn
from ..runtime import TrainerRuntime
from .core_evaluation import register_core_evaluation_routes
from .core_sessions import register_core_session_routes
from .core_shared import (
    _build_stream_timings,
    _card_generation_failure_response,
    _record_coach_turn_event,
    _schedule_background_tail,
    drain_background_tail_tasks,
)
from .core_streaming import register_core_stream_routes
from .core_training import register_core_training_routes

__all__ = [
    "CoreRouteDeps",
    "_build_stream_timings",
    "_card_generation_failure_response",
    "_record_coach_turn_event",
    "_request_is_plan_agent_turn",
    "_schedule_background_tail",
    "build_core_router",
    "drain_background_tail_tasks",
    "reset_provider_scheme_cache",
]


@dataclass(slots=True)
class CoreRouteDeps:
    """Strongly-typed domain collaborator context for core sidecar routes."""

    domain: RouterDomainContext
    coach_support_deps: CoachSupportDeps


def build_core_router(
    runtime: TrainerRuntime,
    deps: RouterDeps,
    seed: CoreRouteDeps,
    prepare_research_turn: PrepareResearchTurn,
) -> APIRouter:
    del deps
    router = APIRouter()
    session_message = register_core_session_routes(
        router,
        runtime,
        seed,
        prepare_research_turn,
    )
    register_core_stream_routes(
        router,
        runtime,
        seed,
        prepare_research_turn,
        session_message_handler=session_message,
    )
    register_core_evaluation_routes(router, runtime, seed)
    register_core_training_routes(router, runtime, seed)
    return router
