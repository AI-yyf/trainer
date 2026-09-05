from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

NEWAPI_CONNECTION_TYPE = "newapi_channel_conn"
NEWAPI_CONNECTION_ALIASES = frozenset(
    {
        "newapi_channel_conn",
        "newapi",
        "new-api",
        "new_api",
        "oneapi",
        "one-api",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderGatewayFingerprint:
    kind: str
    connection_type: str | None
    version: str | None
    catalog_endpoint_types: tuple[str, ...]


def normalize_provider_connection_type(value: str | None) -> str | None:
    """Connection types are not protocols. Unknown values stay unknown."""
    if not isinstance(value, str):
        return None
    normalized = "_".join(value.strip().lower().split())
    if not normalized:
        return None
    if normalized in NEWAPI_CONNECTION_ALIASES:
        return NEWAPI_CONNECTION_TYPE
    return None


def inspect_provider_gateway_headers(
    headers: Mapping[str, str] | None,
    *,
    catalog_endpoint_types: tuple[str, ...] = (),
) -> ProviderGatewayFingerprint:
    if not headers:
        return ProviderGatewayFingerprint(
            kind="unknown",
            connection_type=None,
            version=None,
            catalog_endpoint_types=catalog_endpoint_types,
        )
    lowered = {
        str(key).strip().lower(): str(value).strip()
        for key, value in headers.items()
        if str(value).strip()
    }
    version = lowered.get("x-new-api-version") or None
    oneapi_request = lowered.get("x-oneapi-request-id")
    if version or oneapi_request:
        return ProviderGatewayFingerprint(
            kind="newapi",
            connection_type=NEWAPI_CONNECTION_TYPE,
            version=version,
            catalog_endpoint_types=catalog_endpoint_types,
        )
    return ProviderGatewayFingerprint(
        kind="unknown",
        connection_type=None,
        version=None,
        catalog_endpoint_types=catalog_endpoint_types,
    )


def catalog_endpoint_type_claims(payload: object | None) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    data = payload.get("data")
    if not isinstance(data, list):
        return ()
    claimed: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            continue
        raw_types = item.get("supported_endpoint_types") or item.get("supportedEndpointTypes")
        if not isinstance(raw_types, list):
            continue
        for entry in raw_types:
            if not isinstance(entry, str):
                continue
            normalized = entry.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            claimed.append(normalized)
    return tuple(claimed)


def gateway_fingerprint_diagnostics(fingerprint: ProviderGatewayFingerprint) -> tuple[str, ...]:
    if fingerprint.kind == "newapi":
        version = f" {fingerprint.version}" if fingerprint.version else ""
        claims = (
            f" Catalog claimed endpoint types: {', '.join(fingerprint.catalog_endpoint_types)}."
            if fingerprint.catalog_endpoint_types
            else ""
        )
        return (
            (
                f"Gateway fingerprint: {NEWAPI_CONNECTION_TYPE} (New API{version})."
                " Catalog endpoint types are claims, not live protocol evidence."
                " Unknown fields will not be sent."
                f"{claims}"
            ),
        )
    return (
        (
            "Gateway fingerprint: unknown."
            " Trainer will not assume OpenAI-compatible until a live protocol probe succeeds."
        ),
    )
