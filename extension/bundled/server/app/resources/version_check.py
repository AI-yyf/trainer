"""Read-only comparison of captured source content."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from ..core.models import ResourceRecord
from .canonical import normalize_canonical_body
from .capture import CaptureError, capture_source, capture_url_from_tags, capture_url_key

VersionCheckStatus = Literal[
    "unchanged", "changed", "no_source", "no_baseline", "network_disabled", "fetch_failed",
    "stale", "missing",
]
VersionCheckBasis = Literal["page", "pdf", "repository", "indexed_url"]


class ResourceVersionCheckResult(BaseModel):
    resource_id: str
    version_id: str
    content_hash: str
    status: VersionCheckStatus
    basis: VersionCheckBasis | None = None


_SNAPSHOT = re.compile(
    r"\A---\ntitle: [^\n]*\nsource: (?P<url>[^\n]+)\ncaptured_at: [^\n]+"
    r"\ncapture_kind: (?P<kind>web|github_repo)\nselection: false\n---\n\n"
    r"#[ \t]+[^\n]+\n\n(?P<body>.+)\Z",
    re.DOTALL,
)
_REPOSITORY_DOCS = "\n\n## Repository docs/ layout\n\n"


def is_capture_provenance_tag(tag: str) -> bool:
    return tag in {"capture-selection", "docs-supplemented"} or tag.startswith((
        "trainer-capture:", "captured-from:", "capture-key:", "capture-domain:",
        "captured-at:", "capture-intent:", "capture-location:", "capture-content:",
    ))


def effective_capture_tags(resource: ResourceRecord) -> tuple[str, ...]:
    if resource.capture_provenance_tags:
        return tuple(resource.capture_provenance_tags)
    return tuple(tag for tag in resource.tags if is_capture_provenance_tag(tag))


def captured_source_kind(resource: ResourceRecord) -> str:
    return next(
        (tag.removeprefix("trainer-capture:") for tag in effective_capture_tags(resource)
         if tag.startswith("trainer-capture:")),
        "",
    )


def compare_captured_source(
    resource: ResourceRecord,
    kind: str,
    saved_snapshot: str,
    *,
    network_enabled: bool,
) -> tuple[VersionCheckStatus, VersionCheckBasis | None]:
    tags = effective_capture_tags(resource)
    if "capture-selection" in tags or any(tag.startswith("capture-intent:") for tag in tags):
        return "no_baseline", None

    url = capture_url_from_tags(tags)
    if not url or capture_url_key(url) not in tags:
        url = ""
    body = ""
    if kind == "pdf":
        basis: VersionCheckBasis = "pdf"
        # md-only stores the Markdown digest as record.content_hash; the
        # captured PDF digest remains in the provenance tag.
        saved_fingerprint = next(
            (tag.removeprefix("capture-content:") for tag in tags
             if tag.startswith("capture-content:")),
            "",
        )
    elif kind in {"web", "github_repo"}:
        basis = "repository" if kind == "github_repo" else "page"
        snapshot = _SNAPSHOT.fullmatch(saved_snapshot.replace("\r\n", "\n"))
        if snapshot and snapshot["kind"] == kind:
            url = url or snapshot["url"]
            body = snapshot["body"].strip()
        else:
            # md-only: the durable baseline is the canonical Markdown body,
            # not the deleted capture snapshot. The snapshot's fingerprint
            # starts after its H1, so strip the canonical H1 too.
            body = re.sub(r"\A#\s+[^\n]+\n+", "", saved_snapshot.strip(), count=1)
        if not body:
            return "no_baseline", basis
        saved_fingerprint = normalize_canonical_body(body, "")
    else:
        return "no_baseline", None

    if not url or not saved_fingerprint:
        return "no_baseline", basis
    if not network_enabled:
        return "network_disabled", basis

    include_docs = basis == "repository" and _REPOSITORY_DOCS in body
    try:
        captured = capture_source(kind, url, include_docs=include_docs, network_enabled=True)
    except CaptureError:
        return "fetch_failed", basis
    if captured.kind != kind:
        return "changed", basis
    if kind == "pdf":
        current_fingerprint = captured.content_hash
    else:
        current = _SNAPSHOT.fullmatch(captured.content.replace("\r\n", "\n"))
        if not current or (include_docs and captured.warnings):
            return "fetch_failed", basis
        current_fingerprint = normalize_canonical_body(current["body"].strip(), "")
    return ("unchanged" if current_fingerprint == saved_fingerprint else "changed"), basis
