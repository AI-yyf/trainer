from __future__ import annotations

from app.api.runtime import TrainerRuntime
from app.core.models import ProviderCapabilityEvidence, ProviderConfig, ProviderTestResponse


def verified_capability_result(*, tools: bool = True, vision: bool = False) -> ProviderTestResponse:
    """Return explicit mock observations; declarations alone never satisfy gates."""

    evidence = [
        ProviderCapabilityEvidence(
            name="streaming",
            declared=True,
            observed=True,
            state="verified",
        ),
        ProviderCapabilityEvidence(
            name="tools",
            declared=tools,
            observed=True if tools else None,
            state="verified" if tools else "disabled",
        ),
    ]
    if vision:
        evidence.append(
            ProviderCapabilityEvidence(
                name="vision",
                declared=True,
                observed=True,
                state="verified",
            )
        )

    return ProviderTestResponse(
        ok=True,
        detail="test fixture: observed streaming, tool, and optional vision capability",
        capability_evidence=evidence,
        streaming_ready=True,
        stream_probe_status="verified",
        tools_ready=tools,
        tool_probe_status="verified" if tools else "disabled",
        vision_ready=vision,
        vision_probe_status="verified" if vision else "unverified",
    )


def seed_verified_capabilities(
    runtime: TrainerRuntime,
    provider: ProviderConfig,
    api_key: str,
    *,
    tools: bool = True,
    vision: bool | None = None,
) -> None:
    """Seed only test runtime state with explicit observed capability evidence."""

    if vision is None:
        vision = bool(provider.capabilities.vision)
    result = verified_capability_result(tools=tools, vision=vision)
    runtime.remember_provider_capability_test(provider, api_key, result)
    current_service = runtime.provider_service
    if (
        getattr(current_service, "_config", None) == provider
        and getattr(current_service, "_api_key", None) == api_key
    ):
        current_service._capability_truth = {
            item.name: item.state for item in result.capability_evidence
        }
