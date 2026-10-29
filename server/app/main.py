from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .affect.service import AffectService
from .api.admission import browse_only_rejection
from .api.routers import build_router
from .api.routes.insights import build_insights_router
from .api.routes.research import build_research_router
from .api.routes.telemetry import build_telemetry_router
from .api.routes.training_attempts import build_training_attempts_router
from .api.routes.training_handoff import build_training_handoff_router
from .api.runtime import TrainerRuntime
from .browser_bridge import BrowserBridgeService
from .core.config import Settings
from .core.event_ledger import EventLedgerService
from .core.settings import AppSettings
from .db.repository import TrainerRepository
from .db.research_repository import ResearchRepository
from .evaluator.service import EvaluatorService
from .ingest.service import IngestService
from .llm.provider_service import ProviderService
from .memory.semantic import SemanticMemory
from .memory.service import MemoryService
from .pedagogy.service import PedagogyService
from .planner.service import PlannerService
from .resources.service import ResourceService
from .resources.versioning import ResourceVersionStore
from .sandbox.service import SandboxService
from .specs.service import SpecService
from .telemetry.service import TelemetryService
from .training.attempt_store import AttemptStore
from .training.card_generator import CardGenerationService
from .training.card_router import CardRouterService
from .training.plan_revision import PlanRevisionStore
from .workspace.root_scope_recovery import recover_legacy_root_registrations
from .workspace.runtime_path_recovery import recover_runtime_paths


def create_app(settings_override: Settings | AppSettings | None = None) -> FastAPI:
    settings = settings_override or Settings()
    data_dir = settings.data_dir  # type: ignore[attr-defined]
    database_path = settings.database_path  # type: ignore[attr-defined]
    data_dir.mkdir(parents=True, exist_ok=True)

    repository = TrainerRepository(database_path)
    try:
        recover_legacy_root_registrations(repository)
    except (sqlite3.DatabaseError, ValueError):
        logging.getLogger(__name__).warning(
            "Legacy Trainer registration recovery was unavailable; current scoped data was preserved."
        )
    attempt_store = AttemptStore(database_path)
    plan_revision_store = PlanRevisionStore(database_path)
    resource_version_store = ResourceVersionStore(database_path)
    recover_runtime_paths(database_path, data_dir)
    research_db_path = data_dir / "research.db"
    research_repository = ResearchRepository(research_db_path)
    qdrant_path = settings.qdrant_path if isinstance(settings, Settings) else data_dir / "qdrant"
    semantic_memory = SemanticMemory(qdrant_path)
    memory_service = MemoryService(repository)
    event_ledger = EventLedgerService()
    provider_service = ProviderService()
    network_fetch_enabled = bool(getattr(settings, "enable_network_fetch", False))
    resource_service = ResourceService(
        repository,
        IngestService(network_fetch_enabled=network_fetch_enabled),
        semantic_memory,
        enable_network_fetch=network_fetch_enabled,
        data_root=data_dir,
    )
    memory_service.set_resource_dedupe_hook(resource_service.dedupe_resources)
    browser_bridge = BrowserBridgeService(data_dir)

    runtime = TrainerRuntime(
        repository=repository,
        attempt_store=attempt_store,
        plan_revision_store=plan_revision_store,
        resource_version_store=resource_version_store,
        research_repository=research_repository,
        research_network_fetch_enabled=network_fetch_enabled,
        provider_service=provider_service,
        planner_service=PlannerService(repository=repository),
        memory_service=memory_service,
        resource_service=resource_service,
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
        pedagogy_service=PedagogyService(),
        affect_service=AffectService(),
        card_generation_service=CardGenerationService(
            provider_service=provider_service,
            event_ledger=event_ledger,
        ),
        card_router_service=CardRouterService(event_ledger=event_ledger),
        event_ledger=event_ledger,
        browser_bridge=browser_bridge,
    )
    runtime.hydrate_provider_capability_cache()
    runtime.telemetry_service = TelemetryService(event_ledger, data_dir)
    runtime.sandbox_service = SandboxService(
        data_root=data_dir,
        event_ledger=event_ledger,
        workspace_path_resolver=runtime.resolve_workspace_path,
        workspace_sandbox_root_resolver=runtime.resolve_workspace_sandbox_root,
        workspace_authority_resolver=runtime.workspace_authority,
    )
    resource_service.set_workspace_path_resolver(runtime.resolve_workspace_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A restart orphans the previous process's in-flight training saves;
        # expire them honestly (failed/recoverable) at startup instead of
        # letting stale `executing` records linger until their timeout.
        runtime.memory_service.expire_in_flight_training_reliability_at_startup()
        runtime.bind_organizer_loop(asyncio.get_running_loop())
        organizer_task = asyncio.create_task(runtime.run_background_resource_organizer())
        yield
        organizer_task.cancel()
        sweep_task = getattr(runtime, "_organizer_sweep_task", None)
        if sweep_task is not None:
            sweep_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await organizer_task
        from .llm.mcp_client import aclose_runtime_mcp_sessions

        await aclose_runtime_mcp_sessions(runtime)
        runtime.resource_service.close()

    app = FastAPI(title="Trainer Sidecar", version="0.1.0", lifespan=lifespan)

    # TR-077 (per-instance auth token): the extension generates a random token
    # per sidecar launch and passes it via TRAINER_SIDECAR_TOKEN; every request
    # must carry it. When unset (manual dev launch), the guard stays open.
    #
    # The Trainer Capture browser extension cannot read the per-instance token
    # (it authenticates with its own pairing credential), so the browser-facing
    # lane is exempt by path: /browser/pair, /browser/status, the draft compose
    # route, and a Bearer-authenticated /resources/capture. /browser/pair-code
    # stays inside the trusted boundary — the workbench host registers codes
    # there. The pending-drafts read/ack routes are host-facing too (the host is
    # their only consumer), so they stay inside this boundary as well.
    instance_token = os.getenv("TRAINER_SIDECAR_TOKEN", "").strip()
    browser_lane_paths = frozenset(
        {
            "/browser/status",
            "/browser/auto-pair",
            "/browser/coach-draft",
        }
    )

    def browser_lane_request(request: Request) -> bool:
        path = request.url.path.rstrip("/") or "/"
        if path == "/browser/pair":
            # T-0045: the exemption is method-scoped. The browser's code
            # exchange (POST) and a Bearer-authenticated self-revoke (DELETE)
            # ride the lane; the bearer-less host revoke requires the
            # instance token — otherwise any local process could revoke the
            # user's pairing.
            method = request.method.upper()
            if method == "POST":
                return True
            if method == "DELETE":
                authorization = str(request.headers.get("authorization") or "").strip().lower()
                return authorization.startswith("bearer ")
            return False
        if path in browser_lane_paths:
            return True
        if path == "/resources/capture":
            authorization = str(request.headers.get("authorization") or "").strip().lower()
            return authorization.startswith("bearer ")
        return False

    @app.middleware("http")
    async def instance_token_guard(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if (
            instance_token
            and not browser_lane_request(request)
            and request.headers.get("x-trainer-token") != instance_token
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Trainer sidecar requires the per-instance token."},
            )
        return await call_next(request)

    @app.middleware("http")
    async def browse_only_admission_guard(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        rejection = await browse_only_rejection(request)
        if rejection is not None:
            return rejection
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(runtime))
    app.include_router(build_research_router(runtime.research_service, runtime.provider_service))
    app.include_router(build_training_handoff_router(runtime))
    app.include_router(build_training_attempts_router(runtime))
    app.include_router(build_insights_router(runtime))
    app.include_router(build_telemetry_router(runtime))
    app.state.runtime = runtime
    app.state.settings = settings
    return app


app = create_app()
