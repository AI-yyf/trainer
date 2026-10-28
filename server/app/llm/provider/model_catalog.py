"""Model catalog discovery and caching for ProviderService (§五十二 extraction)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

import httpx

from ...core.models import ProviderConfig, ProviderModelsResponse, ProviderModelTokenLimit
from ..provider.errors import provider_http_failure
from ..provider_gateway import (
    catalog_endpoint_type_claims,
    gateway_fingerprint_diagnostics,
    inspect_provider_gateway_headers,
)
from .redaction import redact_provider_error
from .service_support import extract_model_token_limit as _extract_model_token_limit

_NATIVE_MODEL_DISCOVERY_MAX_PAGES = 20
_NATIVE_MODEL_DISCOVERY_MAX_MODELS = 2000
_ANTHROPIC_MODELS_PAGE_SIZE = 100
_GEMINI_MODELS_PAGE_SIZE = 100


class ModelCatalogMixin:
    if TYPE_CHECKING:
        _MODEL_CACHE_TTL_SECONDS: float
        _config: ProviderConfig | None
        _models_cache: dict[tuple[str, str], tuple[float, ProviderModelsResponse]]
        _classify_error: Callable[..., Any]
        _configured_protocol: Callable[..., Any]
        _create_sync_client: Callable[..., Any]
        _detail_from_category: Callable[..., Any]
        _direct_http_client: Callable[..., Any]
        _normalized_openai_compatible_base_url: Callable[..., Any]
        _anthropic_base_url: Callable[..., Any]


    def _provider_cache_key(self, provider: ProviderConfig, api_key: str | None) -> tuple[str, str]:
        try:
            provider_fingerprint = json.dumps(
                provider.model_dump(mode="json", by_alias=True, exclude_none=True),
                ensure_ascii=True,
                sort_keys=True,
            )
        except Exception:
            provider_fingerprint = repr(provider)
        api_key_fingerprint = hashlib.sha256(
            (api_key.strip() if isinstance(api_key, str) else "").encode("utf-8")
        ).hexdigest()
        return (provider_fingerprint, api_key_fingerprint)

    def _get_cached_models(self, provider: ProviderConfig, api_key: str | None) -> ProviderModelsResponse | None:
        cache_key = self._provider_cache_key(provider, api_key)
        cached = self._models_cache.get(cache_key)
        if not cached:
            return None
        cached_at, response = cached
        if monotonic() - cached_at > self._MODEL_CACHE_TTL_SECONDS:
            self._models_cache.pop(cache_key, None)
            return None
        return response.model_copy(update={"cache_hit": True})

    def _store_cached_models(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        response: ProviderModelsResponse,
    ) -> None:
        # An incomplete catalog must not be pinned in the cache: the next
        # discovery should retry pagination instead of serving a truncated
        # directory for the whole TTL.
        if not response.listed or response.incomplete:
            return
        cache_key = self._provider_cache_key(provider, api_key)
        self._models_cache[cache_key] = (monotonic(), response.model_copy(update={"cache_hit": False}))

    def _resolve_model(self, override: str | None = None) -> str:
        if override and override.strip():
            return override.strip()
        if self._config and self._config.model.strip():
            return self._config.model.strip()
        return "gpt-4o-mini"

    def _model_candidates(self, override: str | None = None) -> list[str]:
        primary = self._resolve_model(override)
        normalized = primary.strip()
        candidates: list[str] = []

        def add(candidate: str | None) -> None:
            value = candidate.strip() if isinstance(candidate, str) else ""
            if value and value not in candidates:
                candidates.append(value)

        add(normalized)
        lowered = normalized.lower()
        add(lowered)
        add(lowered.replace(".", "-"))
        add(lowered.replace("-", "."))
        add(lowered.replace("_", "-"))
        add(lowered.replace("_", "."))
        add(lowered.replace(".", "").replace("-", "").replace("_", ""))

        if lowered == "mimo-v2.5" or normalized == "MiMo-V2.5":
            add("mimo-v2.5")
            add("mimo-v2.5-pro")

        return candidates

    def _normalize_model_id(self, value: object) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None

    def _resolve_model_from_list(self, requested_model: str, available_models: list[str]) -> str | None:
        requested = requested_model.strip()
        if not requested or not available_models:
            return None

        requested_lower = requested.lower()
        normalized_candidates = self._model_candidates(requested)
        available_by_lower = {model.lower(): model for model in available_models}
        available_by_flat = {
            model.lower().replace(".", "").replace("-", "").replace("_", ""): model
            for model in available_models
        }

        for candidate in normalized_candidates:
            direct = available_by_lower.get(candidate.lower())
            if direct:
                return direct

            flattened = candidate.lower().replace(".", "").replace("-", "").replace("_", "")
            fuzzy = available_by_flat.get(flattened)
            if fuzzy:
                return fuzzy

        return available_by_lower.get(requested_lower)

    def _models_response_from_ids(
        self,
        provider: ProviderConfig,
        models: list[str],
        *,
        diagnostics: list[str],
        listed: bool = True,
        model_token_limits: dict[str, ProviderModelTokenLimit] | None = None,
        incomplete: bool = False,
    ) -> ProviderModelsResponse:
        unique_models = sorted({model for model in models if model}, key=str.lower)
        has_visible_models = bool(unique_models)
        resolved = self._resolve_model_from_list(provider.model, unique_models)
        resolved_from_input = bool(resolved and resolved != provider.model)
        normalized_model_token_limits = {
            model_name: limit
            for model_name, limit in (model_token_limits or {}).items()
            if model_name in unique_models
        }
        detail = (
            f"Fetched {len(unique_models)} models."
            if unique_models
            else "Provider responded, but did not return any visible models."
        )
        if resolved:
            detail += f" Resolved configured model to {resolved}."
        if incomplete:
            detail += " Catalog may be incomplete: listing stopped before the provider finished."
        return ProviderModelsResponse(
            ok=has_visible_models,
            detail=detail,
            available_models=unique_models,
            resolved_model=resolved,
            model_token_limits=normalized_model_token_limits,
            resolved_from_input=resolved_from_input,
            listed=listed and has_visible_models,
            diagnostics=[
                *diagnostics,
                f"Listed {len(unique_models)} models from provider {provider.name}.",
                *( [f"Resolved configured model to {resolved}."] if resolved else [] ),
            ],
            incomplete=incomplete,
        )

    def _anthropic_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native anthropic_messages model listing."]
        url = f"{self._anthropic_base_url(provider)}/v1/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with self._direct_http_client(provider, timeout=60.0) as client:
            response = client.get(url, headers=headers, params={"limit": _ANTHROPIC_MODELS_PAGE_SIZE})
            if response.status_code >= 400:
                if not self._anthropic_base_url_is_official(provider):
                    return self._anthropic_fallback_to_openai_model_list(
                        provider,
                        api_key,
                        diagnostics=diagnostics,
                        failure_detail=redact_provider_error(
                            {"upstream_body": response.text},
                            api_key=api_key,
                            fallback=f"Anthropic Models list failed (HTTP {response.status_code})",
                        ),
                    )
                raise provider_http_failure(
                    response,
                    detail=redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Anthropic Models list failed (HTTP {response.status_code})",
                    )
                )
            body = response.json()
            models, model_token_limits, incomplete = self._walk_native_model_pages(
                api_key=api_key,
                client=client,
                url=url,
                headers=headers,
                first_body=body,
                protocol_label="Anthropic",
                has_more=lambda page: bool(page.get("has_more")),
                cursor_of=lambda page: self._string_body_field(page, "last_id"),
                params_with_cursor=lambda cursor: {"limit": _ANTHROPIC_MODELS_PAGE_SIZE, "after_id": cursor},
                collect_items=self._anthropic_page_model_items,
                diagnostics=diagnostics,
            )
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
            incomplete=incomplete,
        )

    def _anthropic_page_model_items(self, body: dict[str, Any]) -> Iterator[tuple[str, ProviderModelTokenLimit | None]]:
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = self._normalize_model_id(item.get("id"))
            if model_id:
                yield model_id, _extract_model_token_limit(item)

    @staticmethod
    def _string_body_field(body: dict[str, Any], key: str) -> str | None:
        value = body.get(key)
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _anthropic_base_url_is_official(provider: ProviderConfig) -> bool:
        return "anthropic.com" in str(provider.base_url or "").strip().lower()

    def _anthropic_fallback_to_openai_model_list(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        diagnostics: list[str],
        failure_detail: str,
    ) -> ProviderModelsResponse:
        """Retry discovery with the common gateway-compatible list endpoint.

        Several non-Anthropic gateways accept the Messages request shape but
        expose discovery only through the OpenAI-compatible /models endpoint.
        This fallback is intentionally limited to third-party endpoints; the
        official API remains on its native transport.
        """
        fallback = self._openai_list_models(provider, api_key)
        return fallback.model_copy(
            update={
                "diagnostics": [
                    *diagnostics,
                    "Native Anthropic model listing was unavailable on this gateway; tried OpenAI-compatible /models.",
                    failure_detail,
                    *fallback.diagnostics,
                ],
            }
        )

    def _gemini_models_endpoint(self, provider: ProviderConfig) -> str:
        base_url = str(provider.base_url or "").strip().rstrip("/")
        if not base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta"
        if base_url.endswith(":generateContent"):
            base_url = base_url.rsplit("/models/", 1)[0] if "/models/" in base_url else base_url
        if "/models/" in base_url:
            base_url = base_url.rsplit("/models/", 1)[0]
        if base_url.rstrip("/").endswith("/models"):
            return base_url
        if base_url.endswith("/v1") or base_url.endswith("/v1beta"):
            return f"{base_url}/models"
        return f"{base_url}/v1beta/models"

    def _gemini_base_url_is_google_native(self, provider: ProviderConfig) -> bool:
        return "googleapis.com" in str(provider.base_url or "").strip().lower()

    def _gemini_fallback_to_openai_model_list(
        self,
        provider: ProviderConfig,
        api_key: str,
        *,
        diagnostics: list[str],
        failure_detail: str,
    ) -> ProviderModelsResponse:
        diagnostics = [
            *diagnostics,
            "Native Gemini model listing did not return usable models on a non-Google endpoint; trying OpenAI-compatible /models for this gateway.",
            failure_detail,
        ]
        fallback = self._openai_list_models(provider, api_key)
        return fallback.model_copy(
            update={
                "diagnostics": [*diagnostics, *fallback.diagnostics],
            }
        )

    def _gemini_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        diagnostics = ["Using native gemini_generate_content model listing."]
        url = self._gemini_models_endpoint(provider)
        headers = {
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        }
        with self._direct_http_client(provider, timeout=60.0) as client:
            response = client.get(url, headers=headers, params={"pageSize": _GEMINI_MODELS_PAGE_SIZE})
            if response.status_code >= 400:
                if not self._gemini_base_url_is_google_native(provider):
                    return self._gemini_fallback_to_openai_model_list(
                        provider,
                        api_key,
                        diagnostics=diagnostics,
                        failure_detail=redact_provider_error(
                            {"upstream_body": response.text},
                            api_key=api_key,
                            fallback=f"Gemini Models list failed (HTTP {response.status_code})",
                        ),
                    )
                raise provider_http_failure(
                    response,
                    detail=redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=f"Gemini Models list failed (HTTP {response.status_code})",
                    )
                )
            body = response.json()
            models, model_token_limits, incomplete = self._walk_native_model_pages(
                api_key=api_key,
                client=client,
                url=url,
                headers=headers,
                first_body=body,
                protocol_label="Gemini",
                has_more=lambda page: bool(page.get("nextPageToken")),
                cursor_of=lambda page: self._string_body_field(page, "nextPageToken"),
                params_with_cursor=lambda cursor: {"pageSize": _GEMINI_MODELS_PAGE_SIZE, "pageToken": cursor},
                collect_items=self._gemini_page_model_items,
                diagnostics=diagnostics,
            )
        if not models and not self._gemini_base_url_is_google_native(provider):
            return self._gemini_fallback_to_openai_model_list(
                provider,
                api_key,
                diagnostics=diagnostics,
                failure_detail="Gemini Models list returned HTTP 200 but no usable native models.",
            )
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=diagnostics,
            model_token_limits=model_token_limits,
            incomplete=incomplete,
        )

    def _gemini_page_model_items(self, body: dict[str, Any]) -> Iterator[tuple[str, ProviderModelTokenLimit | None]]:
        for item in body.get("models") or []:
            if not isinstance(item, dict):
                continue
            raw_name = self._normalize_model_id(item.get("name"))
            if not raw_name:
                continue
            yield raw_name.removeprefix("models/"), _extract_model_token_limit(item)

    def _walk_native_model_pages(
        self,
        *,
        api_key: str,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        first_body: dict[str, Any],
        protocol_label: str,
        has_more: Callable[[dict[str, Any]], bool],
        cursor_of: Callable[[dict[str, Any]], str | None],
        params_with_cursor: Callable[[str], dict[str, Any]],
        collect_items: Callable[[dict[str, Any]], Iterator[tuple[str, ProviderModelTokenLimit | None]]],
        diagnostics: list[str],
    ) -> tuple[list[str], dict[str, ProviderModelTokenLimit], bool]:
        """Walk cursor pages after a successful first page.

        Returns ``(models, model_token_limits, incomplete)``. A failure on a
        later page keeps every page fetched so far and reports the catalog as
        incomplete instead of discarding the whole directory.
        """
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        seen: set[str] = set()
        body = first_body
        pages = 1
        for model_id, token_limit in collect_items(body):
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append(model_id)
            if token_limit is not None:
                model_token_limits[model_id] = token_limit
        while has_more(body):
            cursor = cursor_of(body)
            if not cursor:
                diagnostics.append(
                    f"{protocol_label} reported more models without a pagination cursor; "
                    f"returning the {len(seen)} models fetched so far."
                )
                return models, model_token_limits, True
            if pages >= _NATIVE_MODEL_DISCOVERY_MAX_PAGES:
                diagnostics.append(
                    f"{protocol_label} listing stopped after {_NATIVE_MODEL_DISCOVERY_MAX_PAGES} pages; "
                    "the provider reported more models."
                )
                return models, model_token_limits, True
            if len(seen) >= _NATIVE_MODEL_DISCOVERY_MAX_MODELS:
                diagnostics.append(
                    f"{protocol_label} listing stopped at {_NATIVE_MODEL_DISCOVERY_MAX_MODELS} models; "
                    "the provider reported more models."
                )
                return models, model_token_limits, True
            pages += 1
            try:
                response = client.get(url, headers=headers, params=params_with_cursor(cursor))
            except Exception as exc:
                diagnostics.append(
                    redact_provider_error(
                        exc,
                        api_key=api_key,
                        fallback=(
                            f"{protocol_label} listing interrupted on page {pages}; "
                            "returning the models fetched so far."
                        ),
                    )
                )
                return models, model_token_limits, True
            if response.status_code >= 400:
                diagnostics.append(
                    redact_provider_error(
                        {"upstream_body": response.text},
                        api_key=api_key,
                        fallback=(
                            f"{protocol_label} listing stopped on page {pages} "
                            f"(HTTP {response.status_code}); returning the models fetched so far."
                        ),
                    )
                )
                return models, model_token_limits, True
            try:
                body = response.json()
            except ValueError:
                diagnostics.append(
                    f"{protocol_label} listing stopped on page {pages}: the response was not valid JSON; "
                    "returning the models fetched so far."
                )
                return models, model_token_limits, True
            for model_id, token_limit in collect_items(body):
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                models.append(model_id)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit
        return models, model_token_limits, False

    @staticmethod
    def _iter_listed_models(response: object) -> list[object]:
        """Iterate a models.list payload without treating MagicMock as a catalog."""
        data = getattr(response, "data", None)
        if isinstance(data, list):
            return data
        if isinstance(response, list):
            return response
        module = type(response).__module__
        if module.startswith("unittest.mock"):
            return []
        iterator = getattr(response, "__iter__", None)
        if not callable(iterator):
            return []
        try:
            return list(cast("list[object]", response))
        except TypeError:
            return []

    def _openai_list_models(self, provider: ProviderConfig, api_key: str) -> ProviderModelsResponse:
        client = self._create_sync_client(provider, api_key)
        response = client.models.list()
        models: list[str] = []
        model_token_limits: dict[str, ProviderModelTokenLimit] = {}
        notes: list[str] = []

        items, incomplete = self._collect_listed_model_items(response, notes)
        for item in items:
            model_id = self._normalize_model_id(getattr(item, "id", None))
            if model_id:
                models.append(model_id)
                token_limit = _extract_model_token_limit(item)
                if token_limit is not None:
                    model_token_limits[model_id] = token_limit

        protocol = self._configured_protocol(provider)
        listing_note = (
            f"Using OpenAI-shaped model listing as a catalog probe for provider {provider.name}."
            if protocol is None
            else f"Using OpenAI-compatible model listing for provider {provider.name}."
        )
        return self._models_response_from_ids(
            provider,
            models,
            diagnostics=[listing_note, *notes],
            model_token_limits=model_token_limits,
            incomplete=incomplete,
        )

    def _collect_listed_model_items(self, response: object, notes: list[str]) -> tuple[list[object], bool]:
        """Materialize catalog items, following SDK cursor pagination when offered.

        Some OpenAI-compatible gateways page /models via ``has_more`` plus a
        cursor, which the SDK exposes through ``auto_paging_iter``; endpoints
        that return everything at once behave exactly as before. Consumption is
        bounded so a misbehaving endpoint cannot loop forever, and an
        interruption keeps the items collected so far (reported incomplete).
        """
        auto_iterator = self._auto_paging_iterator(response)
        if auto_iterator is None:
            return self._iter_listed_models(response), False
        items: list[object] = []
        try:
            for item in auto_iterator:
                items.append(item)
                if len(items) >= _NATIVE_MODEL_DISCOVERY_MAX_MODELS:
                    notes.append(
                        f"OpenAI-compatible listing stopped at {_NATIVE_MODEL_DISCOVERY_MAX_MODELS} models; "
                        "the provider reported more."
                    )
                    return items, True
        except Exception as exc:
            notes.append(
                redact_provider_error(
                    exc,
                    fallback=(
                        "OpenAI-compatible listing interrupted mid-pagination; "
                        "kept the models fetched so far."
                    ),
                )
            )
            return items, True
        return items, False

    @staticmethod
    def _auto_paging_iterator(response: object) -> Iterator[object] | None:
        """Return the SDK cursor-paging iterator, or None when unavailable."""
        if isinstance(response, list):
            return None
        if type(response).__module__.startswith("unittest.mock"):
            return None
        if not isinstance(getattr(response, "data", None), list):
            return None
        auto = getattr(response, "auto_paging_iter", None)
        if not callable(auto):
            return None
        try:
            iterator = auto()
        except Exception:
            return None
        if not hasattr(iterator, "__iter__"):
            return None
        return cast("Iterator[object]", iterator)

    def _gateway_fingerprint_diagnostics(
        self,
        provider: ProviderConfig,
        api_key: str,
    ) -> list[str]:
        base_url = self._normalized_openai_compatible_base_url(provider)
        if not base_url:
            return []
        try:
            with self._direct_http_client(provider, timeout=2.0) as client:
                response = client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            catalog_claims = catalog_endpoint_type_claims(
                response.json() if response.status_code < 400 else None
            )
            fingerprint = inspect_provider_gateway_headers(
                response.headers,
                catalog_endpoint_types=catalog_claims,
            )
            return list(gateway_fingerprint_diagnostics(fingerprint))
        except Exception:
            return []

    def list_models(
        self,
        provider: ProviderConfig,
        api_key: str | None,
        *,
        skip_cache: bool = False,
    ) -> ProviderModelsResponse:
        if not api_key:
            return ProviderModelsResponse(
                ok=False,
                detail="Provider config is saved, but no API key is available. Trainer cannot fetch models until you add one.",
                error_category="missing_api_key",
                retryable=False,
                diagnostics=["No API key supplied for model listing."],
            )

        if not skip_cache:
            cached = self._get_cached_models(provider, api_key)
            if cached is not None:
                return cached

        try:
            protocol = self._configured_protocol(provider)
            if protocol == "anthropic_messages":
                result = self._anthropic_list_models(provider, api_key)
            elif protocol == "gemini_generate_content":
                result = self._gemini_list_models(provider, api_key)
            else:
                result = self._openai_list_models(provider, api_key)
            self._store_cached_models(provider, api_key, result)
            return result
        except Exception as exc:  # pragma: no cover - network dependent
            category, retryable, status_code, _, _ = self._classify_error(exc)
            return ProviderModelsResponse(
                ok=False,
                detail=self._detail_from_category(category, provider=provider, error=exc),
                error_category=category,
                retryable=retryable,
                status_code=status_code,
                diagnostics=[
                    "Model listing request failed.",
                    redact_provider_error(exc, api_key=api_key),
                ],
            )

