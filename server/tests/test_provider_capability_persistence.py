"""Provider capability truth survives sidecar restarts.

Before: the capability cache was process memory only — every sidecar
restart wiped it and the user had to re-run "Test Connection" before any
streaming action worked again. Now the truth is persisted in the sidecar
database and hydrated back at boot (pi-agent-style: state on disk).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
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
        base_url="http://minimax.relay.example.test",
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


def _passed_test_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "ok": True,
        "checkedAt": datetime.now(UTC).isoformat(),
        "baseUrl": "http://minimax.relay.example.test",
        "model": "MiniMax-M2.7",
        "capabilityEvidence": [
            {"name": "connection", "declared": True, "observed": True, "state": "verified"},
            {"name": "streaming", "declared": True, "observed": True, "state": "verified"},
            {"name": "tools", "declared": True, "observed": True, "state": "verified"},
        ],
    }
    record.update(overrides)
    return record


def test_host_recorded_test_restores_capability_after_a_data_root_switch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    service = runtime.provider_service_for(provider, "sk-test")
    request = SimpleNamespace(last_test_result=_passed_test_record())

    runtime.adopt_request_provider_evidence(request, service)

    assert runtime.provider_connection_verified(service)
    assert runtime.provider_capability_state_for(service, "streaming") == "verified"
    assert runtime.provider_capability_state_for(service, "tools") == "verified"

    # The adopted evidence is persisted, so the next process does not need the
    # request at all.
    runtime_two = create_app(settings).state.runtime
    service_two = runtime_two.provider_service_for(provider, "sk-test")
    assert runtime_two.provider_connection_verified(service_two)
    assert runtime_two.provider_capability_state_for(service_two, "streaming") == "verified"


def test_stale_or_mismatched_host_evidence_never_unlocks_the_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    runtime = create_app(settings).state.runtime
    provider = _provider()
    service = runtime.provider_service_for(provider, "sk-test")

    stale = _passed_test_record(
        checkedAt=(datetime.now(UTC) - timedelta(hours=2)).isoformat()
    )
    runtime.adopt_request_provider_evidence(SimpleNamespace(last_test_result=stale), service)
    assert not runtime.provider_connection_verified(service)

    mismatched = _passed_test_record(model="another-model")
    runtime.adopt_request_provider_evidence(
        SimpleNamespace(last_test_result=mismatched), service
    )
    assert not runtime.provider_connection_verified(service)

    failed = _passed_test_record(ok=False)
    runtime.adopt_request_provider_evidence(SimpleNamespace(last_test_result=failed), service)
    assert not runtime.provider_connection_verified(service)


def test_session_message_request_keeps_host_last_test_evidence() -> None:
    from app.core.models import SessionMessageRequest

    record = _passed_test_record()
    for payload in (
        {"message": "hello", "lastTestResult": record},
        {"message": "hello", "last_test_result": record},
    ):
        request = SessionMessageRequest.model_validate(payload)
        assert request.last_test_result is not None
        assert request.last_test_result.get("ok") is True
