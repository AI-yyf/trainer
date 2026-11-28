"""(j) Browser / network intake boundary: external content enters only through the
    capture lane, and fetches cannot reach private networks.

Guarantees covered:
  * the browser bridge pairs with explicit credentials, persists and revokes them across restarts;
  * captures are mocked at the upstream fetch boundary, deduped by normalized URL, and land as library Markdown;
  * controlled fetch rejects non-public DNS answers, redirects to private ranges, and oversized bodies.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_network_fetch.py
  * server/tests/test_browser_bridge.py
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.browser_bridge import BrowserBridgeService, BrowserPairingError, build_coach_draft_text
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

# ---------------------------------------------------------------------------
# Restored from test_network_fetch.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


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


def _target_with(addresses: list[tuple[int, tuple[object, ...]]]) -> _ResolvedTarget:
    return _ResolvedTarget(
        url="http://source.example/article",
        scheme="http",
        host="source.example",
        port=80,
        request_target="/article",
        addresses=tuple(
            _ResolvedAddress(family, socket.IPPROTO_TCP, sockaddr)
            for family, sockaddr in addresses
        ),
    )


def test_controlled_fetch_prefers_ipv4_when_dns_returns_aaaa_first(monkeypatch) -> None:
    attempted: list[tuple[int, tuple[object, ...]]] = []

    class FakeSocket:
        def __init__(self, family: int) -> None:
            self.family = family

        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, sockaddr: tuple[object, ...]) -> None:
            attempted.append((self.family, sockaddr))

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "app.network_fetch.socket.socket",
        lambda family, *_args, **_kwargs: FakeSocket(family),
    )
    target = _target_with(
        [
            (socket.AF_INET6, ("2606:4700::1", 80, 0, 0)),
            (socket.AF_INET, ("93.184.216.34", 80)),
        ]
    )

    connected = ControlledHttpFetcher()._connect_verified(target)

    assert connected.family == socket.AF_INET
    assert attempted == [(socket.AF_INET, ("93.184.216.34", 80))]


def test_controlled_fetch_falls_back_to_ipv6_after_ipv4_refusal(monkeypatch) -> None:
    attempted: list[int] = []

    class FakeSocket:
        def __init__(self, family: int) -> None:
            self.family = family

        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, _sockaddr: tuple[object, ...]) -> None:
            attempted.append(self.family)
            if self.family == socket.AF_INET:
                raise ConnectionRefusedError("refused")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "app.network_fetch.socket.socket",
        lambda family, *_args, **_kwargs: FakeSocket(family),
    )
    target = _target_with(
        [
            (socket.AF_INET6, ("2606:4700::1", 80, 0, 0)),
            (socket.AF_INET, ("93.184.216.34", 80)),
        ]
    )

    connected = ControlledHttpFetcher()._connect_verified(target)

    assert connected.family == socket.AF_INET6
    assert attempted == [socket.AF_INET, socket.AF_INET6]


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
    import types

    monkeypatch.setattr(
        "app.resources.ingest._trafilatura_module",
        types.SimpleNamespace(
            extract=lambda *_args, **_kwargs: None,
            bare_extraction=lambda *_args, **_kwargs: document,
        ),
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
    import types

    monkeypatch.setattr(
        "app.resources.ingest._trafilatura_module",
        types.SimpleNamespace(
            extract=lambda *_args, **_kwargs: None,
            bare_extraction=lambda *_args, **_kwargs: {
                "title": "Dictionary extraction",
                "text": "  Extracted from a dict result.  ",
                "author": "Grace Hopper",
                "date": "2026-07-13",
                "url": "https://untrusted.example/dict-source",
            },
        ),
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
    import types

    monkeypatch.setattr(
        "app.resources.ingest._trafilatura_module",
        types.SimpleNamespace(
            extract=lambda *_args, **_kwargs: "",
            bare_extraction=lambda *_args, **_kwargs: None,
        ),
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


def test_web_search_excerpt_prefers_article_content_over_navigation() -> None:
    html = (
        "<html><body><nav>" + ("menu " * 500) + "</nav>"
        "<main><article><h1>Dependency Injection</h1>"
        "<p>Testing overrides replace dependencies safely.</p></article></main>"
        "</body></html>"
    )

    excerpt = WebSearchClient(network_enabled=True)._extract_text_from_html(html, 200)

    assert excerpt == "Dependency Injection Testing overrides replace dependencies safely."


def test_web_search_falls_back_to_bing_when_duckduckgo_returns_a_challenge(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        calls.append(url)
        if "search.brave.com" in url or "duckduckgo.com" in url:
            body = b'<form id="challenge-form"><div>bot challenge</div></form>'
        elif "bing.com/search" in url:
            body = (
                b'<li class="b_algo"><h2><a href="https://docs.example/guide">'
                b"Verified guide</a></h2></li>"
            )
        else:
            raise AssertionError(f"unexpected URL {url}")
        return ControlledFetchResponse(
            body=body,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-09-19T00:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    results = WebSearchClient(network_enabled=True).search("verified guide", limit=2)

    assert results == [
        {
            "title": "Verified guide",
            "url": "https://docs.example/guide",
            "source": "docs.example",
            "rank": 1,
        }
    ]
    assert "search.brave.com" in calls[0]
    assert "duckduckgo.com" in calls[1]
    assert "bing.com/search" in calls[2]


def test_web_search_parses_brave_site_constrained_results(monkeypatch) -> None:
    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        if url == "https://fastapi.tiangolo.com/sitemap.xml":
            return ControlledFetchResponse(
                body=b"<urlset></urlset>",
                final_url=url,
                status=200,
                headers={"content-type": "application/xml"},
                fetched_at="2026-09-19T00:00:00+00:00",
            )
        assert "search.brave.com" in url
        return ControlledFetchResponse(
            body=(
                b'<div class="snippet" data-type="web"><a href="https://fastapi.tiangolo.com/'
                b'tutorial/dependencies/" class="result l1"><div class="title search-snippet-title" '
                b'title="Dependencies - FastAPI">Dependencies - FastAPI</div></a></div>'
            ),
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            fetched_at="2026-09-19T00:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    results = WebSearchClient(network_enabled=True).search(
        "site:fastapi.tiangolo.com tutorial dependency injection",
        limit=2,
    )

    assert results[0]["title"] == "Dependencies - FastAPI"
    assert results[0]["url"] == "https://fastapi.tiangolo.com/tutorial/dependencies/"


def test_web_search_prefers_first_party_sitemap_for_site_scoped_docs(monkeypatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> ControlledFetchResponse:
        calls.append(url)
        assert url == "https://fastapi.tiangolo.com/sitemap.xml"
        return ControlledFetchResponse(
            body=(
                b"<urlset>"
                b"<url><loc>https://fastapi.tiangolo.com/</loc></url>"
                b"<url><loc>https://fastapi.tiangolo.com/tutorial/dependencies/</loc></url>"
                b"<url><loc>https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/</loc></url>"
                b"<url><loc>https://fastapi.tiangolo.com/advanced/testing-dependencies/</loc></url>"
                b"</urlset>"
            ),
            final_url=url,
            status=200,
            headers={"content-type": "application/xml"},
            fetched_at="2026-09-19T00:00:00+00:00",
        )

    monkeypatch.setattr("app.research.web_search.fetch_url", fake_fetch)
    results = WebSearchClient(network_enabled=True).search(
        "site:fastapi.tiangolo.com dependency injection sub-dependencies testing",
        limit=3,
    )

    assert calls == ["https://fastapi.tiangolo.com/sitemap.xml"]
    assert [result["url"] for result in results] == [
        "https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/",
        "https://fastapi.tiangolo.com/advanced/testing-dependencies/",
    ]


def test_web_search_site_constraint_rejects_irrelevant_fallback_results() -> None:
    client = WebSearchClient(network_enabled=True)
    constrained = client._apply_site_constraint(
        [
            {"title": "Wrong", "url": "https://unrelated.example/tutorial"},
            {"title": "Right", "url": "https://docs.example.org/guide"},
        ],
        "site:example.org verified guide",
    )

    assert constrained == [
        {"title": "Right", "url": "https://docs.example.org/guide"}
    ]


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
    assert result["results"][0]["fetched_at"] == "2026-07-12T00:05:00+00:00"
    assert result["results"][0]["freshness"] == "fresh"
    assert result["results"][0]["trust_score"] == 0.7
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


# ---------------------------------------------------------------------------
# Restored from test_browser_bridge.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def build_client(tmp_path: Path, *, enable_network_fetch: bool = False) -> TestClient:
    settings = AppSettings(
        app_name="Trainer browser bridge",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-browser-bridge.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=enable_network_fetch,
    )
    return TestClient(create_app(settings))


def _start_session(
    client: TestClient,
    workspace_id: str,
    workspace_name: str = "Bridge WS",
    headers: dict[str, str] | None = None,
) -> str:
    started = client.post(
        "/session/start",
        headers=headers,
        json={"workspace_id": workspace_id, "workspace_name": workspace_name},
    )
    assert started.status_code == 200, started.text
    return started.json()["session_id"]


def _pair(client: TestClient, workspace_id: str, code: str = "135790") -> str:
    session_id = _start_session(client, workspace_id)
    registered = client.post(
        "/browser/pair-code",
        json={
            "code": code,
            "expires_in": 600,
            "session_id": session_id,
            "workspace_id": workspace_id,
        },
    )
    assert registered.status_code == 200, registered.text
    paired = client.post("/browser/pair", json={"code": code})
    assert paired.status_code == 200, paired.text
    return str(paired.json()["credential"])


def test_pair_code_registration_rejects_non_six_digit_codes(tmp_path) -> None:
    with build_client(tmp_path) as client:
        session_id = _start_session(client, "workspace-bridge-shape")
        for code in ("12345", "1234567", "abcdef", ""):
            response = client.post(
                "/browser/pair-code",
                json={"code": code, "expires_in": 300, "session_id": session_id},
            )
            assert response.status_code == 422, (code, response.text)
            assert response.json()["detail"]["code"] == "invalid_pair_code"


def test_invalid_credentials_are_refused_without_falling_back(tmp_path) -> None:
    with build_client(tmp_path) as client:
        _start_session(client, "workspace-bridge-auth")
        for header in ("", "Bearer ", "Basic abc", "Bearer not-a-credential"):
            response = client.get(
                "/browser/status",
                headers={"Authorization": header} if header else {},
            )
            assert response.status_code == 401, (header, response.text)


def test_coach_drafts_queue_dedupe_and_ack(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-drafts", code="778899")
        headers = {"Authorization": f"Bearer {token}"}
        first = client.post(
            "/browser/coach-draft",
            json={
                "selection": "The rotation guard runs before the retry queue drains.",
                "url": "https://docs.example.com/rotation",
                "title": "Rotation notes",
                "client_id": "draft-client-1",
            },
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["ok"] is True
        assert first.json()["duplicate"] is False
        assert first.json()["workspace_id"] == "workspace-bridge-drafts"
        draft_id = first.json()["draft_id"]

        repeated = client.post(
            "/browser/coach-draft",
            json={
                "selection": "The rotation guard runs before the retry queue drains.",
                "url": "https://docs.example.com/rotation",
                "title": "Rotation notes",
                "client_id": "draft-client-1",
            },
            headers=headers,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["duplicate"] is True
        assert repeated.json()["draft_id"] == draft_id

        # The host polls and acks on the trusted loopback boundary (no Bearer):
        # it cannot read the browser credential.
        pending = client.get(
            "/browser/pending-drafts",
            params={"workspace_id": "workspace-bridge-drafts"},
        )
        assert pending.status_code == 200, pending.text
        assert pending.json()["workspace_id"] == "workspace-bridge-drafts"
        drafts = pending.json()["drafts"]
        assert [draft["id"] for draft in drafts] == [draft_id]
        assert drafts[0]["workspace_id"] == "workspace-bridge-drafts"
        text = drafts[0]["text"]
        # The draft quotes the selection and cites title + URL, and stays editable text.
        assert "rotation guard" in text
        assert "Rotation notes" in text
        assert "https://docs.example.com/rotation" in text

        acked = client.post(
            "/browser/pending-drafts/ack",
            json={"ids": [draft_id], "workspace_id": "workspace-bridge-drafts"},
        )
        assert acked.status_code == 200, acked.text
        assert acked.json()["removed"] == 1
        assert (
            client.get(
                "/browser/pending-drafts",
                params={"workspace_id": "workspace-bridge-drafts"},
            ).json()["drafts"]
            == []
        )

        # An acked client id does not come back as a fresh duplicate.
        replayed = client.post(
            "/browser/coach-draft",
            json={"selection": "something else", "client_id": "draft-client-1"},
            headers=headers,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["duplicate"] is True


def test_pending_drafts_refuse_an_unscoped_host_call(tmp_path) -> None:
    """Without a workspace reference the sidecar refuses instead of guessing."""

    with build_client(tmp_path) as client:
        _pair(client, "workspace-bridge-scope", code="333333")

        unscoped = client.get("/browser/pending-drafts")
        assert unscoped.status_code == 422, unscoped.text
        assert unscoped.json()["detail"]["code"] == "workspace_required"

        unscoped_ack = client.post("/browser/pending-drafts/ack", json={"ids": ["draft-unknown"]})
        assert unscoped_ack.status_code == 422, unscoped_ack.text
        assert unscoped_ack.json()["detail"]["code"] == "workspace_required"


def test_coach_drafts_require_a_selection_and_a_credential(tmp_path) -> None:
    with build_client(tmp_path) as client:
        token = _pair(client, "workspace-bridge-draft-guard", code="101010")
        headers = {"Authorization": f"Bearer {token}"}
        empty = client.post("/browser/coach-draft", json={"selection": "  "}, headers=headers)
        assert empty.status_code == 422, empty.text
        assert empty.json()["detail"]["code"] == "empty_selection"

        anonymous = client.post("/browser/coach-draft", json={"selection": "hi"})
        assert anonymous.status_code == 401


def test_coach_draft_text_follows_the_workspace_language(tmp_path) -> None:
    chinese = build_coach_draft_text(
        selection="\u8bf7\u89e3\u91ca\u8fd9\u6bb5",
        url="https://docs.example.com/a",
        title="\u7b14\u8bb0",
        language="zh-CN",
    )
    assert chinese.startswith("\u8bf7\u5e2e\u6211\u7406\u89e3\u8fd9\u6bb5\u5185\u5bb9")
    assert "> \u8bf7\u89e3\u91ca\u8fd9\u6bb5" in chinese

    english = build_coach_draft_text(
        selection="Explain this",
        url="https://docs.example.com/a",
        title="Notes",
        language="en-US",
    )
    assert english.startswith("Help me understand this excerpt")


def test_coach_draft_text_covers_all_eight_supported_languages() -> None:
    """A Spanish/Japanese/... workspace gets a natural draft, not English."""

    expected_openers = {
        "zh-CN": "\u8bf7\u5e2e\u6211\u7406\u89e3\u8fd9\u6bb5\u5185\u5bb9",
        "en-US": "Help me understand this excerpt",
        "es-ES": "Ayudame a entender este fragmento",
        "fr-FR": "Aide-moi a comprendre cet extrait",
        "de-DE": "Hilf mir, diesen Ausschnitt zu verstehen",
        "ja-JP": "\u3053\u306e\u629c\u7c8b\u3092\u7406\u89e3\u3057\u305f\u3044\u3067\u3059",
        "ko-KR": "\uc774 \ubc1c\ucdcc\ub97c \uc774\ud574\ud558\uace0 \uc2f6\uc5b4\uc694",
        "pt-BR": "Ajude-me a entender este trecho",
    }
    for language, opener in expected_openers.items():
        text = build_coach_draft_text(
            selection="Retry queues drain after the guard run.",
            url="https://docs.example.com/rotation",
            title="Rotation notes",
            language=language,
        )
        assert text.startswith(opener), (language, text)
        # The excerpt, the title and the URL survive in every language.
        assert "> Retry queues drain after the guard run." in text
        assert "Rotation notes" in text
        assert "https://docs.example.com/rotation" in text

    # A bare base tag still resolves; an unknown language falls back to English.
    assert build_coach_draft_text(selection="x", title="T", language="es").startswith("Ayudame")
    assert build_coach_draft_text(selection="x", title="T", language="xx-YY").startswith("Help me")


def test_browser_lane_paths_are_not_blocked_by_the_instance_token(tmp_path, monkeypatch) -> None:
    """The browser extension cannot read TRAINER_SIDECAR_TOKEN: its lane is exempt."""

    monkeypatch.setenv("TRAINER_SIDECAR_TOKEN", "instance-secret")
    with build_client(tmp_path) as client:
        blocked = client.post(
            "/session/start",
            json={"workspace_id": "ws", "workspace_name": "Blocked"},
        )
        assert blocked.status_code == 401

        session_id = client.post(
            "/session/start",
            json={"workspace_id": "workspace-bridge-token", "workspace_name": "Token lane"},
            headers={"x-trainer-token": "instance-secret"},
        ).json()["session_id"]
        registered = client.post(
            "/browser/pair-code",
            json={"code": "654123", "expires_in": 600, "session_id": session_id},
            headers={"x-trainer-token": "instance-secret"},
        )
        assert registered.status_code == 200, registered.text
        # pair-code itself stays inside the instance-token boundary...
        assert (
            client.post("/browser/pair-code", json={"code": "654123", "expires_in": 600})
            .status_code
            == 401
        )

        paired = client.post("/browser/pair", json={"code": "654123"})
        assert paired.status_code == 200, paired.text
        token = paired.json()["credential"]
        assert (
            client.get("/browser/status", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )

        # ...while the host-facing pending-draft queue stays inside the boundary:
        # the host can present the instance token, the browser lane cannot.
        queue_path = "/browser/pending-drafts"
        blocked_queue = client.get(queue_path, params={"workspace_id": "workspace-bridge-token"})
        assert blocked_queue.status_code == 401, blocked_queue.text
        allowed_queue = client.get(
            queue_path,
            params={"workspace_id": "workspace-bridge-token"},
            headers={"x-trainer-token": "instance-secret"},
        )
        assert allowed_queue.status_code == 200, allowed_queue.text
        assert allowed_queue.json()["drafts"] == []


def test_pending_drafts_survive_sidecar_restart(tmp_path: Path) -> None:
    """T-0009: accepted drafts are durable state, not process memory."""
    data_root = tmp_path / "bridge-data"

    first = BrowserBridgeService(data_root)
    enqueued = first.enqueue_draft(
        workspace_id="ws-drafts",
        selection="persist me across restarts",
        client_id="client-1",
    )
    assert enqueued["ok"] is True and enqueued["duplicate"] is False
    assert len(first.pending_drafts("ws-drafts")) == 1

    restarted = BrowserBridgeService(data_root)
    drafts = restarted.pending_drafts("ws-drafts")
    assert len(drafts) == 1
    assert drafts[0]["id"] == enqueued["draft_id"]
    assert "persist me across restarts" in drafts[0]["text"]

    assert restarted.ack_drafts("ws-drafts", [drafts[0]["id"]]) == 1
    assert restarted.pending_drafts("ws-drafts") == []

    # The ack receipt also survives: the same client capture must not be
    # re-delivered as a "new" draft after yet another restart.
    third = BrowserBridgeService(data_root)
    duplicate = third.enqueue_draft(
        workspace_id="ws-drafts",
        selection="persist me across restarts",
        client_id="client-1",
    )
    assert duplicate["duplicate"] is True
    assert third.pending_drafts("ws-drafts") == []


def test_repeated_wrong_pair_guesses_kill_the_live_pairing_window(tmp_path) -> None:
    """T-0037: /browser/pair is token-exempt, so unrestrained guessing of the
    six-digit code is a credential brute force. After five failed exchanges
    the live pairing window is killed: further guesses — including the
    correct code — require a freshly generated code."""
    with build_client(tmp_path) as client:
        session_id = _start_session(client, "workspace-bridge-brute")
        response = client.post(
            "/browser/pair-code",
            json={
                "code": "012345",
                "expires_in": 600,
                "session_id": session_id,
                "workspace_id": "workspace-bridge-brute",
            },
        )
        assert response.status_code == 200, response.text

        statuses = []
        for guess in ("111111", "222222", "333333", "444444", "555555"):
            guess_response = client.post("/browser/pair", json={"code": guess, "session_id": session_id})
            statuses.append(guess_response.status_code)
        assert statuses == [404, 404, 404, 404, 429], statuses

        # The correct code is consumed by the lockout: no replay of guesses.
        correct = client.post("/browser/pair", json={"code": "012345", "session_id": session_id})
        assert correct.status_code == 429, correct.text

        # A freshly generated code pairs normally again.
        re_register = client.post(
            "/browser/pair-code",
            json={
                "code": "654321",
                "expires_in": 600,
                "session_id": session_id,
                "workspace_id": "workspace-bridge-brute",
            },
        )
        assert re_register.status_code == 200, re_register.text
        ok = client.post("/browser/pair", json={"code": "654321", "session_id": session_id})
        assert ok.status_code == 200, ok.text
        payload = ok.json()
        assert payload.get("token") or payload.get("credential"), payload.keys()


def test_auto_pair_credentials_are_capped_per_workspace(tmp_path) -> None:
    bridge = BrowserBridgeService(tmp_path)
    for _ in range(12):
        bridge.issue_auto_credential(workspace_id="workspace-cap", workspace_name="Cap")
    assert bridge.credential_count() == 10
    # A code-paired credential is never the one that gets pruned.
    bridge.register_pair_code(code="135790", workspace_id="workspace-cap", workspace_name="Cap")
    bridge.exchange_pair_code("135790")
    assert bridge.credential_count() == 11


def test_host_focus_requires_a_workspace(tmp_path) -> None:
    with build_client(tmp_path) as client:
        response = client.post("/browser/host-focus", json={"workspace_id": ""})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_workspace"


def test_revocation_reaches_every_sidecar_process_and_cannot_be_undone(tmp_path: Path) -> None:
    """Two windows run two sidecars over one LibraryRoot and one state file.

    A revocation used to be process-local: the other sidecar kept accepting the
    credential, and its next write put the credential and the trusted origin
    back into the file, so after a restart the revoked browser worked again.
    """
    origin = f"chrome-extension://{'a' * 32}"
    first = BrowserBridgeService(tmp_path)
    first.register_pair_code(code="246810", workspace_id="ws-two-windows", workspace_name="Two windows")
    _first_credential, token = first.exchange_pair_code("246810", origin=origin)

    # A sidecar started later loads the same file and knows the pairing.
    second = BrowserBridgeService(tmp_path)
    assert second.credential_for_token(token, touch=False) is not None
    assert second.is_trusted_extension_origin(origin)

    first.revoke_registered_pairing()

    # The other process refuses the credential from now on...
    assert second.credential_for_token(token, touch=False) is None
    assert not second.is_trusted_extension_origin(origin)

    # ...and nothing it writes afterwards brings it back.
    second.register_pair_code(code="112233", workspace_id="ws-two-windows", workspace_name="Two windows")
    second_credential, second_token = second.exchange_pair_code("112233")
    state = json.loads((tmp_path / "browser_bridge.json").read_text(encoding="utf-8"))
    stored_hashes = {entry["token_hash"] for entry in state["credentials"]}
    assert first.credential_for_token(token, touch=False) is None
    assert first.credential_for_token(second_token, touch=False) is not None
    assert second_credential.token_hash in stored_hashes

    # A fresh process sees the same truth: the revoked browser stays out.
    third = BrowserBridgeService(tmp_path)
    assert third.credential_for_token(token, touch=False) is None
    assert third.credential_for_token(second_token, touch=False) is not None
    assert not third.is_trusted_extension_origin(origin)


def test_auto_credential_rechecks_origin_trust_inside_the_state_lock(tmp_path: Path) -> None:
    """A revoke between the route check and the mint must not mint a credential."""
    bridge = BrowserBridgeService(tmp_path)
    origin = f"chrome-extension://{'b' * 32}"
    with pytest.raises(BrowserPairingError) as raised:
        bridge.issue_auto_credential(
            workspace_id="ws-auto-recheck",
            workspace_name="Auto recheck",
            extension_origin=origin,
        )
    assert raised.value.code == "extension_not_paired"
    assert not (tmp_path / "browser_bridge.json").exists()


def test_paired_in_one_window_is_visible_in_the_other(tmp_path: Path) -> None:
    first = BrowserBridgeService(tmp_path)
    second = BrowserBridgeService(tmp_path)
    second.register_pair_code(code="135791", workspace_id="ws-shared", workspace_name="Shared")
    _credential, token = second.exchange_pair_code("135791")

    assert first.credential_for_token(token, touch=False) is not None
