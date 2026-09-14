"""Provider capability truth survives sidecar restarts.

Before: the capability cache was process memory only — every sidecar
restart wiped it and the user had to re-run "Test Connection" before any
streaming action worked again. Now the truth is persisted in the sidecar
database and hydrated back at boot (pi-agent-style: state on disk).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="MiniMax Relay",
        base_url="http://minimax.redfast.top",
        api_key_ref="trainer.default",
        model="MiniMax-M2.7",
    )


def test_capability_truth_survives_runtime_rebuild(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime_one = create_app(settings).state.runtime
    provider = _provider()

    runtime_one.remember_provider_capability_test(
        provider,
        "sk-test",
        {"ok": True, "capability_evidence": [{"name": "connection", "state": "verified"}]},
    )
    assert runtime_one.provider_connection_verified(
        runtime_one.provider_service_for(provider, "sk-test")
    )

    # 模拟 sidecar 重启:全新运行时,同一个数据库。
    runtime_two = create_app(settings).state.runtime
    service_two = runtime_two.provider_service_for(provider, "sk-test")
    assert runtime_two.provider_connection_verified(service_two), (
        "capability truth must survive a sidecar restart"
    )


def test_failed_test_does_not_persist_as_verified(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test",
        {"ok": False, "capability_evidence": []},
    )
    service = runtime.provider_service_for(provider, "sk-test")
    assert not runtime.provider_connection_verified(service)
