"""Session ids must survive sidecar restarts via durable get_session restore."""

from __future__ import annotations

from pathlib import Path

from app.api.runtime import TrainerRuntime
from app.core.models import ProviderConfig
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.planner.service import PlannerService, TrainingPlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService


def _build_runtime(tmp_path: Path) -> TrainerRuntime:
    repo = TrainerRepository(tmp_path / "trainer.db")
    provider_config = ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_ref="trainer.test",
        model="gpt-4o-mini",
        capabilities={"tools": True, "streaming": True},
    )
    provider_service = ProviderService(
        config=provider_config,
        api_key="sk-test-fake",
    )
    return TrainerRuntime(
        repository=repo,
        provider_service=provider_service,
        planner_service=PlannerService(TrainingPlannerService()),
        memory_service=MemoryService(repo),
        resource_service=ResourceService(
            repo,
            ingest_service=None,  # type: ignore[arg-type]
            semantic_memory=None,  # type: ignore[arg-type]
        ),
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
    )


def test_get_session_rehydrates_from_repository_after_memory_drop(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    state = runtime.start_session("ws-reconnect", "Reconnect Lab")
    session_id = state.session_id
    # Simulate sidecar restart: drop RAM map, keep SQLite.
    runtime.sessions.clear()

    restored = runtime.get_session(session_id)

    assert restored is not None
    assert restored.session_id == session_id
    assert restored.workspace_id == state.workspace_id
    assert session_id in runtime.sessions
