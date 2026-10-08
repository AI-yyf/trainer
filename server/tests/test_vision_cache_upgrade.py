from app.api.runtime import _provider_capability_cache_key
from app.core.models import ProviderConfig
from app.llm.vision_challenge import VISION_PROBE_VERSION
from tests.test_runtime_provider_cache import _make_runtime


def test_upgrade_invalidates_only_legacy_visual_understanding_truth(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    runtime.repository.save_provider_capability("legacy", {
        "connection": "verified", "tools": "verified", "streaming": "verified", "vision": "verified",
    })
    runtime.hydrate_provider_capability_cache()
    assert runtime.provider_capability_cache["legacy"] == {
        "connection": "verified", "tools": "verified", "streaming": "verified", "vision": "unverified",
    }


def test_content_probe_truth_survives_reload_without_retesting_other_capabilities(tmp_path) -> None:
    runtime = _make_runtime(tmp_path)
    config = ProviderConfig(name="visual", base_url="https://example.com/v1", model="visual", api_key_ref="trainer.visual")
    runtime.remember_provider_capability_test(config, "test-key", {
        "ok": True, "capabilityEvidence": [{"name": "vision", "state": "verified"}],
    })
    runtime.provider_capability_cache.clear()
    runtime.hydrate_provider_capability_cache()
    states = runtime.provider_capability_cache[_provider_capability_cache_key(config, "test-key")]
    assert states["vision"] == "verified"
    assert states["vision_probe_version"] == VISION_PROBE_VERSION
    assert states["connection"] == "verified"
