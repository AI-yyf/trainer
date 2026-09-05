from hashlib import sha256

from app.affect.service import AffectService
from app.api.runtime import (
    TrainerRuntime,
    _provider_capability_cache_key,
    _provider_service_cache_key,
)
from app.core.models import (
    CapabilityFlags,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
)
from app.db.repository import TrainerRepository
from app.evaluator.service import EvaluatorService
from app.llm.provider_service import ProviderService
from app.memory.service import MemoryService
from app.pedagogy.service import PedagogyService
from app.planner.service import PlannerService
from app.resources.service import ResourceService
from app.specs.service import SpecService


class _DummyResourceService(ResourceService):
    def __init__(self) -> None:  # pragma: no cover - helper only
        pass


def _make_runtime(tmp_path):
    repository = TrainerRepository(tmp_path / "trainer-runtime-test.db")
    return TrainerRuntime(
        repository=repository,
        provider_service=ProviderService(),
        planner_service=PlannerService(),
        memory_service=MemoryService(repository),
        resource_service=_DummyResourceService(),
        spec_service=SpecService(),
        evaluator_service=EvaluatorService(),
        pedagogy_service=PedagogyService(),
        affect_service=AffectService(),
    )


def test_provider_service_for_reuses_cached_instance(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    config = ProviderConfig(
        name="cached-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.cache",
        model="gpt-4o-mini",
    )

    first = runtime.provider_service_for(config, "sk-test")
    second = runtime.provider_service_for(config, "sk-test")

    assert first is second


def test_provider_service_for_separates_different_provider_keys(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    config = ProviderConfig(
        name="cached-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.cache",
        model="gpt-4o-mini",
    )

    first = runtime.provider_service_for(config, "sk-test")
    second = runtime.provider_service_for(config, "sk-other")

    assert first is not second


def test_provider_service_for_separates_same_provider_with_different_protocols(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    base = {
        "name": "same-visible-provider",
        "base_url": "https://example.com/v1",
        "api_key_ref": "trainer.cache",
        "model": "demo-model",
    }
    chat_config = ProviderConfig(**base, protocol="openai_chat_completions_compatible")
    anthropic_config = ProviderConfig(**base, protocol="anthropic_messages")

    first = runtime.provider_service_for(chat_config, "sk-test")
    second = runtime.provider_service_for(anthropic_config, "sk-test")

    assert first is not second
    assert first._config.protocol == "openai_chat_completions_compatible"  # noqa: SLF001
    assert second._config.protocol == "anthropic_messages"  # noqa: SLF001


def test_provider_service_cache_key_hashes_api_key_without_losing_isolation() -> None:
    config = ProviderConfig(
        name="cached-provider",
        base_url="https://example.com/v1",
        api_key_ref="trainer.cache",
        model="gpt-4o-mini",
    )
    api_key = "sk-runtime-cache-secret"

    first = _provider_service_cache_key(config, api_key)
    same = _provider_service_cache_key(config, api_key)
    other = _provider_service_cache_key(config, "sk-other-runtime-cache-secret")
    default = _provider_service_cache_key(None, api_key)
    expected_digest = sha256(api_key.encode("utf-8")).hexdigest()

    assert first == same
    assert first != other
    assert expected_digest in first
    assert expected_digest in default
    assert api_key not in first
    assert api_key not in default


def test_capability_cache_key_ignores_declared_capabilities() -> None:
    """Declared tools flags must not segment last-test observation cache."""

    base = {
        "name": "transport-provider",
        "base_url": "https://example.com/v1",
        "api_key_ref": "trainer.cache",
        "model": "demo-model",
    }
    with_tools = ProviderConfig(**base, capabilities=CapabilityFlags(tools=True))
    without_tools = ProviderConfig(**base, capabilities=CapabilityFlags(tools=False))
    assert _provider_capability_cache_key(with_tools, "sk-test") == _provider_capability_cache_key(
        without_tools, "sk-test"
    )


def test_failed_last_test_clears_tools_ready_across_declared_capability_variants(
    tmp_path,
) -> None:
    """Cached success under tools=True must not stay tools_ready after a failed last-test."""

    runtime = _make_runtime(tmp_path)
    base = {
        "name": "transport-provider",
        "base_url": "https://example.com/v1",
        "api_key_ref": "trainer.cache",
        "model": "demo-model",
    }
    declared_tools = ProviderConfig(**base, capabilities=CapabilityFlags(tools=True))
    default_tools = ProviderConfig(**base)
    success = ProviderTestResponse(
        ok=True,
        detail="observed tools",
        tools_ready=True,
        tool_probe_status="verified",
        capability_evidence=[
            ProviderCapabilityEvidence(
                name="tools",
                declared=True,
                observed=True,
                state="verified",
            )
        ],
    )
    failure = ProviderTestResponse(
        ok=False,
        detail="auth failed",
        tools_ready=True,
        tool_probe_status="verified",
        capability_evidence=[
            ProviderCapabilityEvidence(
                name="tools",
                declared=True,
                observed=True,
                state="verified",
            )
        ],
    )

    runtime.remember_provider_capability_test(declared_tools, "sk-test", success)
    ready_service = runtime.provider_service_for(declared_tools, "sk-test")
    assert runtime.provider_capability_state_for(ready_service, "tools") == "verified"

    # Pre-fix fragmented sibling key (declared claims used to segment the cache).
    api_digest = sha256(b"sk-test").hexdigest()
    runtime.provider_capability_cache[
        '{"baseUrl": "https://example.com/v1", "capabilities": {"tools": true}, '
        f'"model": "demo-model"}}::{api_digest}'
    ] = {
        "connection": "verified",
        "tools": "verified",
    }

    runtime.remember_provider_capability_test(default_tools, "sk-test", failure)
    assert runtime.provider_capability_state_for(ready_service, "tools") != "verified"
    assert (
        runtime.provider_capability_state_for(
            runtime.provider_service_for(default_tools, "sk-test"),
            "tools",
        )
        != "verified"
    )
    for states in runtime.provider_capability_cache.values():
        assert states.get("tools") != "verified"
        assert states.get("connection") != "verified"


def test_never_tested_capability_cache_does_not_mark_tools_ready(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    config = ProviderConfig(
        name="never-tested",
        base_url="https://example.com/v1",
        api_key_ref="trainer.cache",
        model="demo-model",
        capabilities=CapabilityFlags(tools=True),
    )
    service = runtime.provider_service_for(config, "sk-test")
    assert runtime.provider_capability_state_for(service, "tools") == "unverified"
    assert runtime.provider_connection_verified(service) is False


def test_refresh_workspace_sessions_reads_workspace_state_once(tmp_path) -> None:
    from unittest.mock import Mock

    runtime = _make_runtime(tmp_path)
    first = runtime.start_session("workspace-shared", "First")
    second = runtime.start_session("workspace-shared", "Second")
    snapshot = Mock(wraps=runtime.memory_service.snapshot)
    runtime.memory_service.snapshot = snapshot

    assert runtime.refresh_workspace_sessions("workspace-shared") == 2
    snapshot.assert_called_once_with("workspace-shared")
    assert first.snapshot.memory is not second.snapshot.memory
    if first.snapshot.profile is not None:
        assert first.snapshot.profile is not second.snapshot.profile
    if first.snapshot.plan is not None:
        assert first.snapshot.plan is not second.snapshot.plan
    if first.snapshot.global_plan is not None:
        assert first.snapshot.global_plan is not second.snapshot.global_plan
    if first.snapshot.project_plan_link is not None:
        assert first.snapshot.project_plan_link is not second.snapshot.project_plan_link
