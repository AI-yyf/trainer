"""Shared FastAPI TestClient builder for core server tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import CapabilityFlags, ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path, *, configure_provider: bool = True) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    app = create_app(settings)
    if configure_provider:
        provider = ProviderConfig(
            name="test-openai-compatible",
            baseUrl="http://127.0.0.1:9/v1",
            apiKeyRef="trainer.default",
            model="gpt-4o-mini",
            capabilities=CapabilityFlags(
                chat=True,
                responses=True,
                vision=False,
                embeddings=True,
                tools=False,
                jsonSchema=False,
                streaming=True,
            ),
        )
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    return TestClient(app)
