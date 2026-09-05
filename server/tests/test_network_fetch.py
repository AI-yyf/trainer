from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.network_fetch import (
    ControlledFetchError,
    ControlledFetchResponse,
    ControlledHttpFetcher,
    _ResolvedAddress,
    _ResolvedTarget,
)
from app.research.service import ResearchOrchestratorService
from app.research.web_search import WebSearchClient
from app.resources.ingest import extract_from_url
from app.resources.models import IndexStatus, IngestStatus


def _public_record(ip: str = "93.184.216.34", port: int = 443):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "::",
    ],
)
def test_controlled_fetch_rejects_non_public_dns_answers(monkeypatch, address: str) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    monkeypatch.setattr(
        "app.network_fetch.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)],
    )

    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher()._resolve_target("https://source.example/article")

    assert raised.value.code == "blocked_address"


def test_controlled_fetch_connects_the_vetted_ip_without_re_resolving(monkeypatch) -> None:
    connected_to: list[tuple[object, ...]] = []

    class FakeSocket:
        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, sockaddr: tuple[object, ...]) -> None:
            connected_to.append(sockaddr)

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "app.network_fetch.socket.getaddrinfo",
        lambda *_args, **_kwargs: _public_record(port=80),
    )
    monkeypatch.setattr("app.network_fetch.socket.socket", lambda *_args, **_kwargs: FakeSocket())

    fetcher = ControlledHttpFetcher()
    target = fetcher._resolve_target("http://source.example/article")
    fetcher._connect_verified(target)

    assert connected_to == [("93.184.216.34", 80)]


def test_controlled_fetch_validates_every_redirect_hop(monkeypatch) -> None:
    fetcher = ControlledHttpFetcher()
    resolved_urls: list[str] = []
    responses = iter(
        [
            (302, {"location": "https://second.example/final"}, b""),
            (200, {"content-type": "text/plain"}, b"verified source"),
        ]
    )

    def resolve(url: str) -> _ResolvedTarget:
        resolved_urls.append(url)
        return _ResolvedTarget(
            url=url,
            scheme="https",
            host="source.example",
            port=443,
            request_target="/",
            addresses=(_ResolvedAddress(socket.AF_INET, socket.IPPROTO_TCP, ("93.184.216.34", 443)),),
        )

    monkeypatch.setattr(fetcher, "_resolve_target", resolve)
    monkeypatch.setattr(fetcher, "_request_once", lambda *_args, **_kwargs: next(responses))

    response = fetcher.fetch("https://first.example/start", network_enabled=True)

    assert resolved_urls == ["https://first.example/start", "https://second.example/final"]
    assert response.final_url == "https://second.example/final"
    assert response.body == b"verified source"


def test_controlled_fetch_enforces_the_response_byte_limit() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self._body = b"12345"

        def read(self, size: int) -> bytes:
            chunk, self._body = self._body[:size], self._body[size:]
            return chunk

    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher(max_response_bytes=4)._read_bounded_body(FakeResponse(), {})

    assert raised.value.code == "response_too_large"


def test_controlled_fetch_never_resolves_when_network_is_disabled(monkeypatch) -> None:
    called = False

    def resolve(*_args, **_kwargs):
        nonlocal called
        called = True
        return _public_record()

    monkeypatch.setattr("app.network_fetch.socket.getaddrinfo", resolve)

    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher().fetch("https://source.example", network_enabled=False)

    assert raised.value.code == "network_disabled"
    assert called is False


def test_controlled_fetch_rejects_malformed_urls_with_a_stable_code() -> None:
    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher()._resolve_target("https://[::1")

    assert raised.value.code == "invalid_url"


def test_controlled_fetch_rejects_non_standard_ports_before_dns(monkeypatch) -> None:
    called = False

    def resolve(*_args, **_kwargs):
        nonlocal called
        called = True
        return _public_record()

    monkeypatch.setattr("app.network_fetch.socket.getaddrinfo", resolve)

    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher()._resolve_target("https://source.example:8443/article")

    assert raised.value.code == "non_standard_port"
    assert called is False


def test_controlled_fetch_rejects_hosts_with_too_many_public_addresses(monkeypatch) -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (f"8.8.8.{index}", 443))
        for index in range(1, 4)
    ]
    monkeypatch.setattr("app.network_fetch.socket.getaddrinfo", lambda *_args, **_kwargs: records)

    with pytest.raises(ControlledFetchError) as raised:
        ControlledHttpFetcher(max_resolved_addresses=2)._resolve_target("https://source.example/article")

    assert raised.value.code == "dns_too_many_addresses"


def test_controlled_fetch_applies_the_remaining_deadline_to_each_read(monkeypatch) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def settimeout(self, timeout: float) -> None:
            self.timeouts.append(timeout)

    class FakeResponse:
        def __init__(self) -> None:
            self._body = b"ok"

        def read(self, size: int) -> bytes:
            chunk, self._body = self._body[:size], self._body[size:]
            return chunk

    monotonic_values = iter([95.0, 99.0])
    monkeypatch.setattr("app.network_fetch.time.monotonic", lambda: next(monotonic_values))
    fake_socket = FakeSocket()

    body = ControlledHttpFetcher(timeout_seconds=10)._read_bounded_body(
        FakeResponse(),
        {},
        deadline=100.0,
        sock=fake_socket,
    )

    assert body == b"ok"
    assert fake_socket.timeouts == [5.0, 1.0]


def test_legacy_url_helper_uses_shared_fetch_and_defaults_to_network_disabled(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_fetch(_url: str, **kwargs) -> ControlledFetchResponse:
        calls.append(bool(kwargs["network_enabled"]))
        raise ControlledFetchError("network_disabled", "Network fetch is disabled.")

    monkeypatch.setattr("app.resources.ingest.fetch_url", fake_fetch)

    with pytest.raises(ConnectionError, match="network_disabled"):
        extract_from_url("https://example.com/legacy-helper")

    assert calls == [False]


def test_legacy_url_helper_preserves_verified_final_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.resources.ingest.fetch_url",
        lambda _url, **_kwargs: ControlledFetchResponse(
            body=b"<html><body>Verified legacy source.</body></html>",
            final_url="https://final.example/legacy-source",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-12T00:00:00+00:00",
        ),
    )
    extracted = extract_from_url("https://origin.example/legacy-source", network_enabled=True)

    assert extracted.text == "Verified legacy source."
    assert extracted.url == "https://final.example/legacy-source"


def test_legacy_url_helper_supports_trafilatura_document_results(monkeypatch) -> None:
    from trafilatura.settings import Document

    document = Document(
        title="Document extraction",
        text="  Extracted from a Document result.  ",
        author="Ada Lovelace",
        date="2026-07-13",
        url="https://untrusted.example/document-source",
    )
    monkeypatch.setattr(
        "app.resources.ingest.fetch_url",
        lambda _url, **_kwargs: ControlledFetchResponse(
            body=b"<html><body>ignored by the fake extractor</body></html>",
            final_url="https://final.example/document-source",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-13T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        "app.resources.ingest.trafilatura.bare_extraction",
        lambda *_args, **_kwargs: document,
    )

    extracted = extract_from_url("https://origin.example/document-source", network_enabled=True)

    assert extracted.title == "Document extraction"
    assert extracted.text == "Extracted from a Document result."
    assert extracted.author == "Ada Lovelace"
    assert extracted.date == "2026-07-13"
    assert extracted.url == "https://final.example/document-source"


def test_legacy_url_helper_supports_trafilatura_dict_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.resources.ingest.fetch_url",
        lambda _url, **_kwargs: ControlledFetchResponse(
            body=b"<html><body>ignored by the fake extractor</body></html>",
            final_url="https://final.example/dict-source",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-13T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        "app.resources.ingest.trafilatura.bare_extraction",
        lambda *_args, **_kwargs: {
            "title": "Dictionary extraction",
            "text": "  Extracted from a dict result.  ",
            "author": "Grace Hopper",
            "date": "2026-07-13",
            "url": "https://untrusted.example/dict-source",
        },
    )

    extracted = extract_from_url("https://origin.example/dict-source", network_enabled=True)

    assert extracted.title == "Dictionary extraction"
    assert extracted.text == "Extracted from a dict result."
    assert extracted.author == "Grace Hopper"
    assert extracted.date == "2026-07-13"
    assert extracted.url == "https://final.example/dict-source"


def test_legacy_url_helper_rejects_empty_trafilatura_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.resources.ingest.fetch_url",
        lambda _url, **_kwargs: ControlledFetchResponse(
            body=b"<html><body>ignored by the fake extractor</body></html>",
            final_url="https://final.example/empty-source",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-13T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        "app.resources.ingest.trafilatura.bare_extraction",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(ValueError, match="No extractable content"):
        extract_from_url("https://origin.example/empty-source", network_enabled=True)


def test_url_indexing_keeps_network_disabled_sources_unfetched_and_unready(tmp_path) -> None:
    settings = AppSettings(
        app_name="Trainer controlled fetch test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="controlled-fetch.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    resource_service = app.state.runtime.resource_service
    with patch.object(resource_service.semantic_memory, "upsert_text") as upsert_text:
        with TestClient(app) as client:
            uploaded = client.post(
                "/resource/upload",
                json={
                    "workspace_id": "workspace-network-disabled",
                    "kind": "url",
                    "name": "Disabled source",
                    "source": "https://example.com/source",
                },
            )
            assert uploaded.status_code == 200
            indexed = client.post(
                "/resource/index",
                json={
                    "workspace_id": "workspace-network-disabled",
                    "resource_id": uploaded.json()["id"],
                    "enable_network": True,
                },
            )

    assert indexed.status_code == 200
    payload = indexed.json()
    assert payload["parse_status"] == "failed"
    assert payload["index_status"] == "failed"
    assert payload["fetched_at"] is None
    assert payload["freshness"] == "unknown"
    assert "network_disabled" in payload["quality_flags"]
    registry_resource = resource_service.registry.get(payload["id"])
    assert registry_resource is not None
    assert registry_resource.ingest_status is IngestStatus.FAILED
    assert registry_resource.index_status is IndexStatus.FAILED
    upsert_text.assert_not_called()


def test_url_indexing_keeps_original_source_and_records_verified_final_url(tmp_path) -> None:
    settings = AppSettings(
        app_name="Trainer controlled fetch test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="controlled-fetch-success.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    fetched = ControlledFetchResponse(
        body=b"<html><body><p>Verified snapshot.</p></body></html>",
        final_url="https://final.example/snapshot",
        status=200,
        headers={"content-type": "text/html"},
        fetched_at="2026-07-12T00:00:00+00:00",
    )
    app = create_app(settings)
    resource_service = app.state.runtime.resource_service
    with patch("app.ingest.service.fetch_url", return_value=fetched):
        with TestClient(app) as client:
            uploaded = client.post(
                "/resource/upload",
                json={
                    "workspace_id": "workspace-network-success",
                    "kind": "url",
                    "name": "Redirected source",
                    "source": "https://origin.example/start",
                },
            )
            assert uploaded.status_code == 200
            indexed = client.post(
                "/resource/index",
                json={
                    "workspace_id": "workspace-network-success",
                    "resource_id": uploaded.json()["id"],
                    "enable_network": True,
                },
            )

    assert indexed.status_code == 200
    payload = indexed.json()
    assert payload["source"] == "https://origin.example/start"
    assert payload["canonical_source"] == "https://final.example/snapshot"
    assert payload["fetched_at"] == "2026-07-12T00:00:00+00:00"
    assert payload["freshness"] == "fresh"
    assert payload["parse_status"] == "parsed"
    assert payload["index_status"] == "indexed"
    assert any("content_type=text/html" in warning for warning in payload["warnings"])
    registry_resource = resource_service.registry.get(payload["id"])
    assert registry_resource is not None
    assert registry_resource.metadata["source_provenance"] == {
        "status": "fetched",
        "final_url": "https://final.example/snapshot",
        "fetched_at": "2026-07-12T00:00:00+00:00",
        "content_type": "text/html",
    }
    persisted_resource = resource_service.repository.get_resource(
        "workspace-network-success",
        payload["id"],
    )
    assert persisted_resource is not None
    assert any("content_type=text/html" in warning for warning in persisted_resource.warnings)


def test_research_web_search_obeys_the_shared_network_switch(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        calls.append(url)
        return ControlledFetchResponse(
            body=b"<html><body>safe source</body></html>",
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-12T00:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    disabled = WebSearchClient(network_enabled=False)
    enabled = WebSearchClient(network_enabled=True)

    assert disabled.fetch_page_content("https://example.com") == ""
    assert calls == []
    assert enabled.fetch_page_content("https://example.com") == "safe source"
    assert calls == ["https://example.com"]


def test_research_search_reports_page_fetch_failures_without_recording_live_findings(monkeypatch) -> None:
    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        if "duckduckgo.com" in url:
            return ControlledFetchResponse(
                body=(
                    b'<a class="result-link" href="https://blocked.example/source">'
                    b"Blocked source</a>"
                ),
                final_url=url,
                status=200,
                headers={"content-type": "text/html"},
                fetched_at="2026-07-12T00:00:00+00:00",
            )
        raise ControlledFetchError("blocked_address", "URL host resolved to a non-public address.")

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    service = ResearchOrchestratorService(network_enabled=True)

    result = service.search_web("controlled fetch", workspace_id="workspace-research-failure")

    assert result["reason_code"] == "blocked_address"
    assert result["results"] == []
    assert "No results found" not in result.get("message", "")
    assert service.recent_background_references(workspace_id="workspace-research-failure") == []


def test_research_search_records_verified_page_provenance(monkeypatch) -> None:
    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        if "duckduckgo.com" in url:
            return ControlledFetchResponse(
                body=(
                    b'<a class="result-link" href="https://origin.example/source">'
                    b"Verified research source</a>"
                ),
                final_url=url,
                status=200,
                headers={"content-type": "text/html"},
                fetched_at="2026-07-12T00:00:00+00:00",
            )
        return ControlledFetchResponse(
            body=b"<html><body>Verified research content.</body></html>",
            final_url="https://final.example/source",
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-07-12T00:05:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    service = ResearchOrchestratorService(network_enabled=True)

    result = service.search_web("verified fetch", workspace_id="workspace-research-success")
    references = service.recent_background_references(workspace_id="workspace-research-success")

    assert result["results_count"] == 1
    assert result["results"][0]["url"] == "https://final.example/source"
    assert references[0]["source"] == "https://final.example/source"
    assert references[0]["freshness"] == "fresh"
    assert references[0]["fetched_at"] == "2026-07-12T00:05:00+00:00"


def test_runtime_passes_network_switch_to_research_service(tmp_path) -> None:
    settings = AppSettings(
        app_name="Trainer controlled fetch test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="controlled-fetch-research.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )

    app = create_app(settings)

    assert app.state.runtime.research_network_fetch_enabled is True
    assert app.state.runtime.research_service._web_search.network_enabled is True
