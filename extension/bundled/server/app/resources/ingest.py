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

from app.network_fetch import ControlledFetchError, fetch_url


@dataclass(slots=True)
class ExtractedContent:
    """Structured content extracted from a web page."""

    title: str
    text: str
    author: str | None
    date: str | None
    url: str


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
        msg = f"Controlled URL fetch failed ({exc.code}): {url}"
        raise ConnectionError(msg) from exc

    downloaded = response.body.decode("utf-8", errors="replace")

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
    text = metadata.get("text") or ""
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
