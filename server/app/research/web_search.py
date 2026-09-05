from __future__ import annotations

import re
import urllib.parse
from html import unescape
from typing import Any

from app.network_fetch import ControlledFetchError, fetch_url


class WebSearchClient:
    """Lightweight web search client using DuckDuckGo Lite (no API key required)."""

    def __init__(
        self,
        timeout: int = 15,
        *,
        network_enabled: bool = False,
        max_response_bytes: int = 512 * 1024,
    ) -> None:
        self.timeout = timeout
        self.network_enabled = network_enabled
        self.max_response_bytes = max_response_bytes
        self._user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Perform a web search and return structured results."""
        if not self.network_enabled or not query or not query.strip():
            return []

        try:
            results = self._search_duckduckgo(query.strip(), limit=limit)
            if results:
                return results
        except ControlledFetchError:
            raise
        except Exception:
            pass

        # Fallback: return empty results if search fails
        return []

    def _search_duckduckgo(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search using DuckDuckGo HTML interface."""
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://lite.duckduckgo.com/lite/?q={encoded_query}"

        response = fetch_url(
            url,
            network_enabled=self.network_enabled,
            timeout_seconds=self.timeout,
            max_response_bytes=self.max_response_bytes,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        html = response.body.decode("utf-8", errors="replace")
        return self._parse_duckduckgo_results(html, limit)

    def _parse_duckduckgo_results(self, html: str, limit: int) -> list[dict[str, Any]]:
        """Parse DuckDuckGo Lite HTML results."""
        results: list[dict[str, Any]] = []

        # DuckDuckGo Lite result pattern
        result_blocks = re.findall(
            r'<a[^>]*class="result-link"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        )

        for i, (href, title_html) in enumerate(result_blocks[:limit]):
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            if not title or not href:
                continue

            # Clean up URL
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://duckduckgo.com" + href

            results.append({
                "title": title,
                "url": href,
                "source": self._extract_domain(href),
                "rank": i + 1,
            })

        return results

    def fetch_page(self, url: str, max_length: int = 2000) -> dict[str, str]:
        """Fetch page text together with the verified source provenance."""
        if not self.network_enabled:
            raise ControlledFetchError(
                "network_disabled",
                "Network source acquisition is disabled by Trainer configuration.",
            )
        response = fetch_url(
            url,
            network_enabled=True,
            timeout_seconds=self.timeout,
            max_response_bytes=self.max_response_bytes,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        html = response.body.decode("utf-8", errors="replace")
        return {
            "content": self._extract_text_from_html(html, max_length),
            "final_url": response.final_url,
            "fetched_at": response.fetched_at,
            "content_type": response.content_type,
        }

    def fetch_page_content(self, url: str, max_length: int = 2000) -> str:
        """Fetch page text while preserving the legacy empty-on-failure API."""
        try:
            return self.fetch_page(url, max_length=max_length)["content"]
        except ControlledFetchError:
            return ""

    def _extract_text_from_html(self, html: str, max_length: int) -> str:
        """Extract readable text from HTML."""
        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Remove all remaining HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Decode HTML entities
        text = unescape(text)

        return text[:max_length]

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return url


class SearchResultEnricher:
    """Enrich search results with content snippets."""

    def __init__(self, search_client: WebSearchClient | None = None) -> None:
        self.search_client = search_client or WebSearchClient()

    def enrich(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Search and fetch content snippets for top results."""
        results = self.search_client.search(query, limit=limit)

        enriched = []
        for result in results:
            try:
                page = self.search_client.fetch_page(result["url"], max_length=800)
            except ControlledFetchError as exc:
                enriched.append({
                    **result,
                    "content_snippet": "",
                    "reason_code": exc.code,
                })
                continue

            content = page["content"].strip()
            if not content:
                enriched.append({
                    **result,
                    "content_snippet": "",
                    "reason_code": "no_content",
                })
                continue

            enriched.append({
                **result,
                "url": page["final_url"],
                "content_snippet": content,
                "fetched_at": page["fetched_at"],
                "content_type": page["content_type"],
                "freshness": "fresh",
            })

        return enriched
