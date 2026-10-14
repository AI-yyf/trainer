"""Controlled browser-capture intake for ``POST /resources/capture``.

The Trainer Capture browser extension is a pure data channel: it only sends a
URL, a capture kind and an optional title/selection. Everything that touches the
network happens here, through the same DNS-pinned, size-bounded fetcher used by
URL ingest, and everything that lands in the library goes through the regular
``ResourceService`` upload/index chain.

The intake is a full ingestion pipeline rather than a bookmark:

1. fetch the source through the controlled fetcher (per-kind bounds);
2. clean the readable body (trafilatura first, local HTML fallback);
3. persist a self-describing Markdown snapshot (title, source URL, capture
   time, kind, selection flag) so the material survives the source going away;
4. record metadata as library tags (kind, source domain, normalized URL key,
   capture time, selection flag);
5. index the snapshot through the existing Library FTS chain.

Deduplication aligns with the Library's content-hash mechanism
(``app.resources.versioning.compute_content_hash``): the normalized URL key and
the snapshot hash both answer "is this already in the library?".

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
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.models import ResourceUploadRequest
from app.network_fetch import ControlledFetchError, ControlledFetchResponse, fetch_url

from .ingest import extract_from_url
from .versioning import compute_content_hash

# PDF sources are routinely larger than the 2 MiB default used for HTML/text
# ingest, and a user-initiated download may legitimately outlast the 5 s
# default of an inline URL ingest. Keep hard bounds, but make them fit a real
# paper or slide deck.
PDF_MAX_RESPONSE_BYTES = 25 * 1024 * 1024
PDF_FETCH_TIMEOUT_SECONDS = 45.0

GITHUB_README_API = "https://api.github.com/repos/{owner}/{repo}/readme"
GITHUB_CONTENTS_API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"
_GITHUB_REPO_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_GITHUB_REPO_HOSTS = frozenset({"github.com", "www.github.com"})
_HTTP_STATUS_IN_DETAIL = re.compile(r"HTTP (\d{3})")
_MAX_TITLE_CHARS = 200
_MAX_TAG_CHARS = 240
_MAX_SELECTION_IN_SNAPSHOT = 2000
_MAX_DOCS_LISTING_ENTRIES = 80

# Query parameters that never identify the document: analytics/tracking keys
# are dropped before the URL becomes a dedup key. Fragments and trailing
# slashes are removed as well (``normalize_capture_url``).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "yclid",
    }
)


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
    # Normalized (tracking-free) URL this capture dedupes against.
    capture_url: str = ""
    # SHA-256 of the persisted bytes; the Library content-hash mechanism uses
    # the same digest, so a repeat capture of unchanged content dedupes.
    content_hash: str = ""
    selection_present: bool = False
    source_domain: str = ""
    captured_at: str = ""
    warnings: tuple[str, ...] = ()

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


def normalize_capture_url(value: str) -> str:
    """Normalize a URL into the stable identity used for capture dedup.

    Drops the fragment, tracking query parameters (``utm_*`` and the common
    click ids), redundant default ports and trailing slashes, lowercases the
    scheme/host, and sorts the remaining query parameters so parameter order
    cannot create a second library entry.
    """

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if not scheme or not host:
        return raw
    try:
        port = parsed.port
    except ValueError:
        port = None
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    if parsed.username is not None or parsed.password is not None:
        # Keep userinfo out of the normalized identity entirely.
        netloc = host if port in (None, default_port) else f"{host}:{port}"
    kept_params = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    kept_params.sort()
    query = urlencode(kept_params)
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path == "/":
        path = ""
    return urlunsplit((scheme, netloc, path, query, ""))


def capture_url_key(url: str) -> str:
    """The stable tag value that marks a URL as captured in a library."""

    normalized = normalize_capture_url(url)
    if not normalized:
        return ""
    return f"capture-key:{sha256(normalized.encode('utf-8')).hexdigest()[:24]}"


def capture_url_from_tags(tags: list[str] | tuple[str, ...]) -> str:
    """Best-effort original URL recorded by an earlier capture (display only)."""

    prefix = "captured-from:"
    for tag in tags:
        text = str(tag or "")
        if text.startswith(prefix):
            return text[len(prefix) :]
    return ""


def _is_tracking_param(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if not lowered:
        return False
    if lowered in _TRACKING_PARAM_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)


def capture_source(
    kind: str,
    url: str,
    *,
    network_enabled: bool,
    declared_title: str | None = None,
    selection: str | None = None,
    include_docs: bool = False,
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
        return _capture_web(normalized_url, title_hint, selection=selection)
    if kind == "pdf":
        return _capture_pdf(normalized_url, title_hint)
    if kind == "github_repo":
        return _capture_github_repo(
            normalized_url,
            title_hint,
            include_docs=include_docs,
        )
    raise CaptureError(
        "unsupported_kind",
        f"Unsupported capture kind: {kind}.",
        status_code=422,
    )


def _capture_web(url: str, title_hint: str | None, *, selection: str | None) -> CapturedSource:
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
    selection_text = _clean_selection(selection)
    source_url = extracted.url or url
    snapshot = _compose_markdown_snapshot(
        title=title,
        source_url=source_url,
        kind="web",
        body=extracted.text,
        selection=selection_text,
        extra_sections=(),
    )
    return CapturedSource(
        kind="web",
        source_url=source_url,
        title=title,
        content=snapshot,
        content_encoding=None,
        upload_kind="markdown",
        tags=_capture_tags(
            kind="web",
            display_url=url,
            url_keys=(url, source_url),
            selection=bool(selection_text),
        ),
        capture_url=normalize_capture_url(source_url),
        content_hash=compute_content_hash(snapshot),
        selection_present=bool(selection_text),
        source_domain=_source_domain(source_url),
        captured_at=_utc_now_iso(),
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
    source_url = response.final_url or url
    return CapturedSource(
        kind="pdf",
        source_url=source_url,
        title=title,
        content=base64.b64encode(response.body).decode("ascii"),
        content_encoding="base64",
        upload_kind="pdf",
        tags=_capture_tags(
            kind="pdf",
            display_url=url,
            url_keys=(url, source_url),
            selection=False,
        ),
        capture_url=normalize_capture_url(source_url),
        content_hash=compute_content_hash(response.body),
        selection_present=False,
        source_domain=_source_domain(source_url),
        captured_at=_utc_now_iso(),
    )


def _capture_github_repo(
    url: str,
    title_hint: str | None,
    *,
    include_docs: bool = False,
) -> CapturedSource:
    repo = parse_github_repo(url)
    if repo is None:
        raise CaptureError(
            "not_a_github_repo",
            "A GitHub capture requires a repository URL: https://github.com/<owner>/<repo>.",
            status_code=422,
        )
    owner, name, canonical_url = repo
    readme_text, readme_name = _fetch_github_readme(owner, name)
    warnings: list[str] = []
    extra_sections: tuple[tuple[str, str], ...] = ()
    if include_docs:
        docs_listing = _fetch_github_docs_listing(owner, name)
        if docs_listing:
            extra_sections = (("Repository docs/ layout", docs_listing),)
        else:
            warnings.append(
                "The repository docs/ listing could not be read; the snapshot keeps the README only."
            )
    title = title_hint or f"{owner}/{name}"
    snapshot = _compose_markdown_snapshot(
        title=title,
        source_url=canonical_url,
        kind="github_repo",
        body=readme_text,
        selection=None,
        extra_sections=extra_sections,
    )
    upload_kind: Literal["markdown", "text"] = (
        "markdown" if readme_name.lower().endswith(".md") else "text"
    )
    return CapturedSource(
        kind="github_repo",
        source_url=canonical_url,
        title=title,
        content=snapshot,
        content_encoding=None,
        upload_kind=upload_kind,
        tags=_capture_tags(
            kind="github_repo",
            display_url=canonical_url,
            url_keys=(canonical_url,),
            selection=False,
        ),
        capture_url=normalize_capture_url(canonical_url),
        content_hash=compute_content_hash(snapshot),
        selection_present=False,
        source_domain=_source_domain(canonical_url),
        captured_at=_utc_now_iso(),
        warnings=tuple(warnings),
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


def _fetch_github_docs_listing(owner: str, name: str) -> str:
    """Best-effort listing of the repository's ``docs/`` directory.

    The capture stays honest when the directory is missing or the API rate
    limits the request: the caller records a warning and the snapshot keeps the
    README alone.
    """

    api_url = GITHUB_CONTENTS_API.format(owner=owner, repo=name, path="docs")
    try:
        response = _fetch(api_url, headers={"Accept": "application/vnd.github+json"})
    except CaptureError:
        return ""
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, list):
        return ""
    entries = sorted(
        (
            str(entry.get("path") or "").strip()
            for entry in payload
            if isinstance(entry, dict)
        ),
        key=str.lower,
    )
    visible = [entry for entry in entries if entry]
    if not visible:
        return ""
    lines = [
        f"- `{entry}`" for entry in visible[:_MAX_DOCS_LISTING_ENTRIES]
    ]
    if len(visible) > _MAX_DOCS_LISTING_ENTRIES:
        lines.append(f"- … {len(visible) - _MAX_DOCS_LISTING_ENTRIES} more entries")
    return "\n".join(lines)


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


def parse_github_repo(url: str) -> tuple[str, str, str] | None:
    """Parse a GitHub repository URL into ``(owner, repo, canonical_url)``.

    Returns None when the URL is not a GitHub repository address. The canonical
    URL is the identity used for capturing, deduplication and downloads.
    """
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


def _capture_tags(
    *,
    kind: str,
    display_url: str,
    url_keys: tuple[str, ...],
    selection: bool,
) -> tuple[str, ...]:
    """Library tags that carry the capture metadata.

    ``display_url`` is the URL the capture was requested from (for GitHub, the
    canonical repository URL), ``url_keys`` are the normalized dedup keys — one
    for the requested URL and one for the final (post-redirect) URL when they
    differ, so either side of a redirect matches an earlier capture.
    """

    tags = [
        f"trainer-capture:{kind}",
        f"captured-from:{display_url}"[:_MAX_TAG_CHARS],
    ]
    seen: set[str] = set()
    for url in url_keys:
        key = capture_url_key(url)
        if key and key not in seen:
            seen.add(key)
            tags.append(key)
    domain = _source_domain(display_url)
    if not domain and url_keys:
        domain = _source_domain(url_keys[0])
    if domain:
        tags.append(f"capture-domain:{domain}"[:_MAX_TAG_CHARS])
    tags.append(f"captured-at:{_utc_now_iso()}"[:_MAX_TAG_CHARS])
    if selection:
        tags.append("capture-selection")
    return tuple(tags)


def _compose_markdown_snapshot(
    *,
    title: str,
    source_url: str,
    kind: str,
    body: str,
    selection: str | None,
    extra_sections: tuple[tuple[str, str], ...],
) -> str:
    """Render the durable Markdown snapshot stored in the library.

    The snapshot is self-describing: the front matter keeps the identity of the
    source even after the page changes or disappears, so the resource stays
    useful offline and its provenance stays auditable.
    """

    captured_at = _utc_now_iso()
    lines = [
        "---",
        f"title: {_front_matter_value(title)}",
        f"source: {_front_matter_value(source_url)}",
        f"captured_at: {captured_at}",
        f"capture_kind: {kind}",
        f"selection: {'true' if selection else 'false'}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if selection:
        lines.extend(
            [
                "## Captured selection",
                "",
                "\n".join(f"> {line}" if line else ">" for line in selection.splitlines()),
                "",
            ]
        )
    lines.append(body.strip())
    for section_title, section_body in extra_sections:
        lines.extend(["", f"## {section_title}", "", section_body.strip()])
    lines.append("")
    return "\n".join(lines)


def _front_matter_value(value: str) -> str:
    return " ".join(str(value or "").split()).replace("\n", " ")


def _clean_selection(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= _MAX_SELECTION_IN_SNAPSHOT:
        return text
    return text[: _MAX_SELECTION_IN_SNAPSHOT - 1].rstrip() + "…"


def _source_domain(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


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

