"""Controlled browser-capture intake for ``POST /resources/capture``.

The Trainer Capture browser extension is a pure data channel: it only sends a
URL, a capture kind and an optional title. Everything that touches the network
happens here, through the same DNS-pinned, size-bounded fetcher used by URL
ingest, and everything that lands in the library goes through the regular
``ResourceService`` upload/index chain.

Kinds:
- ``web``: trafilatura extraction of the readable page body.
- ``pdf``: the PDF bytes are downloaded (bounded) and handed to the existing
  PyMuPDF ingest as an owned inline upload.
- ``github_repo``: the repository URL is recorded on the resource and the
  default-branch README is read through the GitHub readme API.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Literal, TypedDict
from urllib.parse import urlsplit

from app.core.models import ResourceUploadRequest
from app.network_fetch import ControlledFetchError, ControlledFetchResponse, fetch_url

from .ingest import extract_from_url

# PDF sources are routinely larger than the 2 MiB default used for HTML/text
# ingest, and a user-initiated download may legitimately outlast the 5 s
# default of an inline URL ingest. Keep hard bounds, but make them fit a real
# paper or slide deck.
PDF_MAX_RESPONSE_BYTES = 25 * 1024 * 1024
PDF_FETCH_TIMEOUT_SECONDS = 45.0

GITHUB_README_API = "https://api.github.com/repos/{owner}/{repo}/readme"
_GITHUB_REPO_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_GITHUB_REPO_HOSTS = frozenset({"github.com", "www.github.com"})
_HTTP_STATUS_IN_DETAIL = re.compile(r"HTTP (\d{3})")
_MAX_TITLE_CHARS = 200
_MAX_TAG_CHARS = 240


class CaptureError(RuntimeError):
    """A display-safe capture failure carrying its HTTP mapping."""

    def __init__(self, code: str, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CapturedSource:
    """One captured source, ready to be uploaded as an owned inline resource."""

    kind: str
    source_url: str
    title: str
    content: str
    content_encoding: Literal["utf-8", "base64"] | None
    upload_kind: Literal["pdf", "markdown", "text"]
    tags: tuple[str, ...]

    def as_upload_request(
        self,
        *,
        session_id: str | None,
        workspace_id: str,
    ) -> ResourceUploadRequest:
        return ResourceUploadRequest(
            session_id=session_id,
            workspace_id=workspace_id,
            kind=self.upload_kind,
            name=self.title,
            source=f"inline://trainer-capture/{self.kind}/{_slug(self.title)}",
            content=self.content,
            content_encoding=self.content_encoding,
            tags=list(self.tags),
        )


def capture_source(
    kind: str,
    url: str,
    *,
    network_enabled: bool,
    declared_title: str | None = None,
) -> CapturedSource:
    """Fetch and extract one browser-captured source.

    ``network_enabled`` is the sidecar's own network boundary switch (the same
    one that gates URL ingest); when it is off the capture is refused instead
    of silently storing a placeholder.
    """

    normalized_url = _validated_http_url(url)
    title_hint = _clean_title(declared_title)
    if not network_enabled:
        raise CaptureError(
            "network_disabled",
            "Network source acquisition is disabled by Trainer configuration "
            "(enable network fetch in Trainer settings).",
            status_code=409,
        )
    if kind == "web":
        return _capture_web(normalized_url, title_hint)
    if kind == "pdf":
        return _capture_pdf(normalized_url, title_hint)
    if kind == "github_repo":
        return _capture_github_repo(normalized_url, title_hint)
    raise CaptureError(
        "unsupported_kind",
        f"Unsupported capture kind: {kind}.",
        status_code=422,
    )


def _capture_web(url: str, title_hint: str | None) -> CapturedSource:
    try:
        extracted = extract_from_url(url, network_enabled=True)
    except ConnectionError as exc:
        raise CaptureError(
            "fetch_failed",
            f"Trainer could not fetch the page: {exc}",
            status_code=502,
        ) from exc
    except ValueError as exc:
        raise CaptureError(
            "empty_content",
            f"Trainer could not extract readable content: {exc}",
            status_code=422,
        ) from exc
    title = title_hint or _clean_title(extracted.title) or _url_display_name(url)
    return CapturedSource(
        kind="web",
        source_url=extracted.url or url,
        title=title,
        content=extracted.text,
        content_encoding=None,
        upload_kind="markdown",
        tags=_capture_tags("web", url),
    )


def _capture_pdf(url: str, title_hint: str | None) -> CapturedSource:
    response = _fetch(
        url,
        max_response_bytes=PDF_MAX_RESPONSE_BYTES,
        timeout_seconds=PDF_FETCH_TIMEOUT_SECONDS,
    )
    if not response.body.startswith(b"%PDF-"):
        raise CaptureError(
            "not_a_pdf",
            "The fetched resource is not a PDF document.",
            status_code=422,
        )
    title = title_hint or _url_display_name(url)
    if not title.lower().endswith(".pdf"):
        # The owned inline file keeps a .pdf suffix so downstream tooling never
        # has to guess the container format from a title.
        title = f"{title}.pdf"
    return CapturedSource(
        kind="pdf",
        source_url=response.final_url or url,
        title=title,
        content=base64.b64encode(response.body).decode("ascii"),
        content_encoding="base64",
        upload_kind="pdf",
        tags=_capture_tags("pdf", url),
    )


def _capture_github_repo(url: str, title_hint: str | None) -> CapturedSource:
    repo = _parse_github_repo(url)
    if repo is None:
        raise CaptureError(
            "not_a_github_repo",
            "A GitHub capture requires a repository URL: https://github.com/<owner>/<repo>.",
            status_code=422,
        )
    owner, name, canonical_url = repo
    readme_text, readme_name = _fetch_github_readme(owner, name)
    title = title_hint or f"{owner}/{name}"
    return CapturedSource(
        kind="github_repo",
        source_url=canonical_url,
        title=title,
        content=readme_text,
        content_encoding=None,
        upload_kind="markdown" if readme_name.lower().endswith(".md") else "text",
        tags=_capture_tags("github_repo", canonical_url),
    )


def _fetch_github_readme(owner: str, name: str) -> tuple[str, str]:
    """Read the default-branch README through the GitHub readme API.

    One request instead of probing file names, and the API resolves whichever
    README variant the repository actually uses.
    """

    api_url = GITHUB_README_API.format(owner=owner, repo=name)
    try:
        response = _fetch(
            api_url,
            headers={"Accept": "application/vnd.github+json"},
        )
    except CaptureError as exc:
        if exc.code == "not_found":
            raise CaptureError(
                "readme_not_found",
                f"Trainer could not find a README for {owner}/{name} (unknown repository or no README on the default branch).",
                status_code=404,
            ) from exc
        raise

    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError(
            "fetch_failed",
            "GitHub returned an unreadable README response.",
            status_code=502,
        ) from exc
    if not isinstance(payload, dict) or str(payload.get("encoding") or "") != "base64":
        raise CaptureError(
            "empty_content",
            "GitHub returned a README payload Trainer cannot decode.",
            status_code=422,
        )
    encoded = str(payload.get("content") or "").strip()
    if not encoded:
        raise CaptureError("empty_content", "The repository README is empty.", status_code=422)
    try:
        text = base64.b64decode(encoded, validate=False).decode("utf-8", errors="replace").strip()
    except (binascii.Error, ValueError) as exc:
        raise CaptureError(
            "empty_content",
            "The repository README could not be decoded.",
            status_code=422,
        ) from exc
    if not text:
        raise CaptureError("empty_content", "The repository README is empty.", status_code=422)
    return text, str(payload.get("name") or "README.md")


class _FetchTuning(TypedDict, total=False):
    """Optional fetch tuning; keeps each unpacked kwarg at its declared type."""

    max_response_bytes: int
    timeout_seconds: float


def _fetch(
    url: str,
    *,
    max_response_bytes: int | None = None,
    timeout_seconds: float | None = None,
    headers: dict[str, str] | None = None,
) -> ControlledFetchResponse:
    options: _FetchTuning = {}
    if max_response_bytes is not None:
        options["max_response_bytes"] = max_response_bytes
    if timeout_seconds is not None:
        options["timeout_seconds"] = timeout_seconds
    try:
        return fetch_url(url, network_enabled=True, headers=headers, **options)
    except ControlledFetchError as exc:
        status = _http_status_from_error(exc)
        if exc.code == "http_status" and status == 404:
            # A missing upstream document is an ordinary "nothing there", not a
            # transport failure the user should diagnose.
            raise CaptureError(
                "not_found",
                f"The source was not found upstream: {url}.",
                status_code=404,
            ) from exc
        raise CaptureError(
            "fetch_failed",
            f"Trainer could not fetch the source ({exc.code}).",
            status_code=502,
        ) from exc


def _http_status_from_error(error: ControlledFetchError) -> int | None:
    match = _HTTP_STATUS_IN_DETAIL.search(str(error.detail or ""))
    return int(match.group(1)) if match else None


def _validated_http_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        raise CaptureError("invalid_url", "Capture requires a non-empty URL.", status_code=422)
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise CaptureError("invalid_url", "URL is invalid.", status_code=422) from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise CaptureError("invalid_url", "Only http and https URLs are allowed.", status_code=422)
    if parsed.username is not None or parsed.password is not None:
        raise CaptureError("invalid_url", "URL userinfo is not allowed.", status_code=422)
    hostname = (parsed.hostname or "").strip().rstrip(".")
    if not hostname:
        raise CaptureError("invalid_url", "URL host is missing.", status_code=422)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CaptureError("invalid_url", "URL port is invalid.", status_code=422) from exc
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if port is not None and port != default_port:
        raise CaptureError(
            "invalid_url",
            "Only standard HTTP and HTTPS ports are allowed.",
            status_code=422,
        )
    if hostname.casefold() in {"localhost", "localhost.localdomain"}:
        raise CaptureError("invalid_url", "Only public URL hosts are allowed.", status_code=422)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise CaptureError("invalid_url", "Only public URL hosts are allowed.", status_code=422)
    return url


def _parse_github_repo(url: str) -> tuple[str, str, str] | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _GITHUB_REPO_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not _GITHUB_REPO_SEGMENT.match(owner) or not _GITHUB_REPO_SEGMENT.match(repo):
        return None
    return owner, repo, f"https://github.com/{owner}/{repo}"


def _capture_tags(kind: str, url: str) -> tuple[str, ...]:
    return (
        f"trainer-capture:{kind}",
        f"captured-from:{url}"[:_MAX_TAG_CHARS],
    )


def _clean_title(value: str | None) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= _MAX_TITLE_CHARS:
        return text
    return text[: _MAX_TITLE_CHARS - 1].rstrip() + "…"


def _url_display_name(url: str) -> str:
    parsed = urlsplit(url)
    last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1].strip()
    return (last_segment or parsed.hostname or "Captured source")[:_MAX_TITLE_CHARS]


def _slug(value: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")
    return slug or "capture"
