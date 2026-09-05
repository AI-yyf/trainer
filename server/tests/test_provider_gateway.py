from app.core.models import ProviderConfig
from app.llm.provider_gateway import (
    NEWAPI_CONNECTION_TYPE,
    catalog_endpoint_type_claims,
    gateway_fingerprint_diagnostics,
    inspect_provider_gateway_headers,
    normalize_provider_connection_type,
)
from app.llm.provider_service import _should_fingerprint_gateway


def test_newapi_connection_type_is_not_guessed_from_unknown_values() -> None:
    assert normalize_provider_connection_type("newapi_channel_conn") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("New API") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("oneapi") == NEWAPI_CONNECTION_TYPE
    assert normalize_provider_connection_type("openai_chat_completions_compatible") is None
    assert normalize_provider_connection_type("mystery-gateway") is None


def test_newapi_headers_fingerprint_does_not_claim_a_protocol() -> None:
    fingerprint = inspect_provider_gateway_headers(
        {
            "x-new-api-version": "v1.0.0-rc.14",
            "x-oneapi-request-id": "abc",
        },
        catalog_endpoint_types=("openai",),
    )
    assert fingerprint.kind == "newapi"
    assert fingerprint.connection_type == NEWAPI_CONNECTION_TYPE
    assert fingerprint.version == "v1.0.0-rc.14"
    diagnostics = gateway_fingerprint_diagnostics(fingerprint)
    assert "newapi_channel_conn" in diagnostics[0]
    assert "not live protocol evidence" in diagnostics[0]
    assert "sk-" not in diagnostics[0]


def test_unknown_gateway_headers_do_not_default_to_compatible() -> None:
    fingerprint = inspect_provider_gateway_headers({"server": "nginx"})
    assert fingerprint.kind == "unknown"
    assert fingerprint.connection_type is None
    assert "not assume OpenAI-compatible" in gateway_fingerprint_diagnostics(fingerprint)[0]


def test_catalog_endpoint_types_are_claims_not_secrets() -> None:
    claims = catalog_endpoint_type_claims(
        {
            "data": [
                {"id": "MiniMax-M2.7", "supported_endpoint_types": ["openai"]},
                {"id": "MiniMax-M3", "supported_endpoint_types": ["openai", "anthropic"]},
            ]
        }
    )
    assert claims == ("openai", "anthropic")


def test_gateway_fingerprint_is_reserved_for_newapi_identity() -> None:
    generic = ProviderConfig(
        name="minimax-provider",
        base_url="https://api.example.com/v1",
        api_key_ref="trainer.minimax",
        model="MiniMax-M3",
    )
    assert _should_fingerprint_gateway(generic) is False
    assert _should_fingerprint_gateway(
        generic.model_copy(update={"connection_type": "newapi_channel_conn"})
    ) is True
    assert _should_fingerprint_gateway(
        generic.model_copy(update={"name": "New API MiniMax"})
    ) is True
