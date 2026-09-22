from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .affect.service import AffectService
from .api.admission import browse_only_rejection
from .api.routers import build_router
from .api.routes.research import build_research_router
from .api.routes.training_attempts import build_training_attempts_router
from .api.routes.training_handoff import build_training_handoff_router
from .api.runtime import TrainerRuntime
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
from .sandbox.service import SandboxService
from .specs.service import SpecService
from .training.attempt_store import AttemptStore
from .training.plan_revision import PlanRevisionStore
from .training.card_generator import CardGenerationService
from .training.card_router import CardRouterService


def create_app(settings_override: Settings | AppSettings | None = None) -> FastAPI:
    settings = settings_override or Settings()
    data_dir = settings.data_dir  # type: ignore[attr-defined]
    database_path = settings.database_path  # type: ignore[attr-defined]
    data_dir.mkdir(parents=True, exist_ok=True)

    repository = TrainerRepository(database_path)
    attempt_store = AttemptStore(database_path)
    plan_revision_store = PlanRevisionStore(database_path)
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

    runtime = TrainerRuntime(
        repository=repository,
        attempt_store=attempt_store,
        plan_revision_store=plan_revision_store,
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
    )
    runtime.hydrate_provider_capability_cache()
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
        yield
        runtime.resource_service.close()

    app = FastAPI(title="Trainer Sidecar", version="0.1.0", lifespan=lifespan)

    # TR-077 (per-instance auth token): the extension generates a random token
    # per sidecar launch and passes it via TRAINER_SIDECAR_TOKEN; every request
    # must carry it. When unset (manual dev launch), the guard stays open.
    instance_token = os.getenv("TRAINER_SIDECAR_TOKEN", "").strip()

    @app.middleware("http")
    async def instance_token_guard(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if instance_token and request.headers.get("x-trainer-token") != instance_token:
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
    app.state.runtime = runtime
    app.state.settings = settings
    return app


app = create_app()
