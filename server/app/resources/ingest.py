from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from importlib import import_module
from typing import Any

try:
    trafilatura: Any | None = import_module("trafilatura")
except ImportError:  # pragma: no cover - optional extraction enhancement
    trafilatura = None

from app.network_fetch import ControlledFetchError, ControlledFetchResponse, fetch_url


@dataclass(slots=True)
class ExtractedContent:
    """Structured content extracted from a web page."""

    title: str
    text: str
    author: str | None
    date: str | None
    url: str


class PdfSourceDetected(ValueError):
    """A fetched URL is a PDF, including URLs without a .pdf suffix."""

    def __init__(self, response: ControlledFetchResponse) -> None:
        super().__init__("The source is a PDF document.")
        self.response = response


class SourceTooLarge(Exception):
    """The page exceeded the web bound and may still be a large PDF."""

    def __init__(self, url: str) -> None:
        super().__init__(f"The source exceeded the web capture size bound: {url}")
        self.url = url


def extract_from_url(url: str, *, network_enabled: bool = False) -> ExtractedContent:
    """Extract readable text and metadata from a controlled URL fetch.

    Args:
        url: The target web page URL.

    Returns:
        An ``ExtractedContent`` dataclass with title, text, author, date and url.

    Raises:
        ConnectionError: If the URL cannot be fetched (network failure, timeout, DNS error).
        ValueError: If no extractable content is found or the extracted text is empty.
    """
    try:
        response = fetch_url(url, network_enabled=network_enabled)
    except ControlledFetchError as exc:
        if exc.code == "response_too_large":
            raise SourceTooLarge(url) from exc
        msg = f"Controlled URL fetch failed ({exc.code}): {url}"
        raise ConnectionError(msg) from exc

    if response.body.startswith(b"%PDF-"):
        raise PdfSourceDetected(response)
    downloaded = response.body.decode("utf-8", errors="replace")

    # The library keeps a readable Markdown document, not the raw HTML page.
    # trafilatura's Markdown output preserves headings, lists, tables, links and
    # inline formatting; the plain-text pass remains the fallback when the
    # optional extractor is unavailable or produces nothing.
    markdown_text = ""
    if trafilatura is not None:
        try:
            markdown_text = (
                trafilatura.extract(
                    downloaded,
                    url=response.final_url,
                    output_format="markdown",
                    include_links=True,
                    include_formatting=True,
                    include_tables=True,
                    include_images=False,
                    favor_recall=True,
                )
                or ""
            ).strip()
        except Exception:
            markdown_text = ""

    if trafilatura is None:
        result = {
            "title": "",
            "text": _html_to_text(downloaded),
            "author": None,
            "date": None,
        }
    else:
        result = trafilatura.bare_extraction(downloaded, with_metadata=True)
    if result is None:
        msg = f"No extractable content found at URL: {url}"
        raise ValueError(msg)

    metadata = result if isinstance(result, dict) else result.as_dict()
    text = markdown_text or metadata.get("text") or ""
    stripped_text = text.strip()
    if not stripped_text:
        msg = f"Extracted content is empty for URL: {url}"
        raise ValueError(msg)

    return ExtractedContent(
        title=metadata.get("title") or "",
        text=stripped_text,
        author=metadata.get("author"),
        date=metadata.get("date"),
        url=response.final_url,
    )


def _html_to_text(content: str) -> str:
    without_non_content = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", without_non_content)
    return unescape(re.sub(r"\s+", " ", text)).strip()
