from __future__ import annotations

import base64
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

        failures: list[ControlledFetchError] = []
        if self._site_constraint_domains(query):
            try:
                sitemap_results = self._search_site_sitemaps(query.strip(), limit=limit)
                if sitemap_results:
                    return sitemap_results
            except ControlledFetchError as exc:
                failures.append(exc)
            except Exception:
                pass
        for searcher in (self._search_brave, self._search_duckduckgo, self._search_bing):
            try:
                results = self._apply_site_constraint(
                    searcher(query.strip(), limit=limit),
                    query,
                )
                if results:
                    return results
            except ControlledFetchError as exc:
                failures.append(exc)
            except Exception:
                continue

        if failures:
            raise failures[-1]

        # Fallback: return empty results if search fails
        return []

    def _search_site_sitemaps(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Resolve site-scoped documentation queries through the site's own sitemap.

        Public search engines often collapse documentation queries to a product home page.
        A declared ``site:`` constraint lets us use the publisher's sitemap as a more precise,
        first-party discovery index while the normal controlled-fetch policy still validates
        DNS, redirects, response size, and scheme.
        """
        query_without_site = re.sub(r"\bsite:([^\s]+)", " ", query, flags=re.IGNORECASE)
        ignored = {
            "and",
            "documentation",
            "docs",
            "for",
            "guide",
            "official",
            "the",
            "tutorial",
            "with",
        }
        query_terms = [
            term
            for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", query_without_site.casefold())
            if term not in ignored
        ]
        # Broad research queries may name several independent facets; no single documentation
        # URL will contain half of all terms. Two path matches are enough to select a concrete
        # first-party page, while a one-term accidental match still falls back to web search.
        minimum_score = 1 if len(query_terms) <= 2 else 2
        ranked: list[tuple[int, int, str]] = []
        for domain in self._site_constraint_domains(query):
            sitemap_url = f"https://{domain}/sitemap.xml"
            response = fetch_url(
                sitemap_url,
                network_enabled=self.network_enabled,
                timeout_seconds=self.timeout,
                max_response_bytes=self.max_response_bytes,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5",
                },
            )
            sitemap = response.body.decode("utf-8", errors="replace")
            for position, raw_url in enumerate(
                re.findall(r"<loc>\s*(.*?)\s*</loc>", sitemap, re.IGNORECASE | re.DOTALL)
            ):
                url = unescape(raw_url).strip()
                if not url.startswith(("http://", "https://")):
                    continue
                if not self._apply_site_constraint([{"url": url}], query):
                    continue
                searchable_url = urllib.parse.unquote(url).casefold()
                normalized_url = searchable_url.replace("ies", "y")
                score = sum(
                    1
                    for term in query_terms
                    if term.replace("ies", "y") in normalized_url
                    or term.replace("ies", "y").rstrip("s") in normalized_url
                )
                if score >= minimum_score:
                    ranked.append((score, -position, url))
        ranked.sort(reverse=True)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _score, _position, url in ranked:
            if url in seen:
                continue
            seen.add(url)
            path = urllib.parse.urlparse(url).path.strip("/")
            title = " / ".join(
                segment.replace("-", " ").replace("_", " ").title()
                for segment in path.split("/")[-2:]
                if segment
            ) or self._extract_domain(url)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "source": self._extract_domain(url),
                    "rank": len(results) + 1,
                }
            )
            if len(results) >= limit:
                break
        return results

    def _search_brave(self, query: str, limit: int) -> list[dict[str, Any]]:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://search.brave.com/search?q={encoded_query}&source=web"
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
        return self._parse_brave_results(html, limit)

    def _search_duckduckgo(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Search using DuckDuckGo HTML interface."""
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

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

    def _search_bing(self, query: str, limit: int) -> list[dict[str, Any]]:
        site_domains = self._site_constraint_domains(query)
        bing_query = re.sub(r"\bsite:([^\s]+)", r"\1", query, flags=re.IGNORECASE)
        if site_domains:
            bing_query = f"{bing_query} official documentation"
        encoded_query = urllib.parse.quote_plus(bing_query)
        url = f"https://www.bing.com/search?q={encoded_query}"
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
        return self._parse_bing_results(html, limit)

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

    def _parse_brave_results(self, html: str, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        matches = re.findall(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*\bl1\b[^"]*"[^>]*>'
            r'.*?<div[^>]*class="[^"]*\btitle\b[^"]*"[^>]*title="([^"]+)"',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for href, raw_title in matches:
            title = unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            url = unescape(href).strip()
            if not title or not url:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "source": self._extract_domain(url),
                    "rank": len(results) + 1,
                }
            )
            if len(results) >= limit:
                break
        return results

    def _parse_bing_results(self, html: str, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        blocks = re.findall(
            r'<li[^>]*class="[^"]*\bb_algo\b[^"]*"[^>]*>(.*?)</li>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for block in blocks:
            match = re.search(
                r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                re.DOTALL | re.IGNORECASE,
            )
            if not match:
                continue
            href = self._decode_bing_redirect(unescape(match.group(1)))
            title = unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            if not title or not href.startswith(("http://", "https://")):
                continue
            results.append(
                {
                    "title": title,
                    "url": href,
                    "source": self._extract_domain(href),
                    "rank": len(results) + 1,
                }
            )
            if len(results) >= limit:
                break
        return results

    def _decode_bing_redirect(self, href: str) -> str:
        try:
            parsed = urllib.parse.urlparse(href)
            if "bing.com" not in parsed.netloc.lower():
                return href
            encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
            if not encoded.startswith("a1"):
                return href
            payload = encoded[2:]
            payload += "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
            return decoded if decoded.startswith(("http://", "https://")) else href
        except (ValueError, UnicodeDecodeError):
            return href

    def _site_constraint_domains(self, query: str) -> list[str]:
        return [
            value.lower().strip("./").removeprefix("www.")
            for value in re.findall(r"\bsite:([^\s]+)", query, flags=re.IGNORECASE)
            if value.strip("./")
        ]

    def _apply_site_constraint(
        self,
        results: list[dict[str, Any]],
        query: str,
    ) -> list[dict[str, Any]]:
        domains = self._site_constraint_domains(query)
        if not domains:
            return results
        return [
            result
            for result in results
            if any(
                self._extract_domain(str(result.get("url") or "")).lower() == domain
                or self._extract_domain(str(result.get("url") or "")).lower().endswith(
                    "." + domain
                )
                for domain in domains
            )
        ]

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

        # Documentation sites often place thousands of navigation characters before the
        # actual page. Prefer the semantic article/main body so the bounded excerpt contains
        # evidence rather than locale menus and table-of-contents chrome.
        article = re.search(
            r"<article\b[^>]*>(.*?)</article>",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if article:
            text = article.group(1)
        else:
            main = re.search(
                r"<main\b[^>]*>(.*?)</main>",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if main:
                text = main.group(1)

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
                page = self.search_client.fetch_page(result["url"], max_length=1600)
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
