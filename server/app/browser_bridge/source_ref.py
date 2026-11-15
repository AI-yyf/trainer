"""Web excerpt provenance shared by the draft queue and the coaching turn."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from ..resources.service import ResourceService


BROWSER_SELECTION_LIMIT = 1200
BROWSER_TITLE_LIMIT = 160
MAX_BROWSER_SOURCES = 8


class BrowserSourceRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(max_length=2048)
    title: str = Field(max_length=BROWSER_TITLE_LIMIT)
    selection: str = Field(min_length=1, max_length=BROWSER_SELECTION_LIMIT)
    resource_id: str | None = Field(default=None, alias="resourceId", max_length=128)
    version_id: str | None = Field(default=None, alias="versionId", max_length=128)
    content_hash: str | None = Field(default=None, alias="contentHash", max_length=128)
    location: dict[str, str] | None = None

    @field_validator("url")
    @classmethod
    def validate_page_url(cls, value: str) -> str:
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("Use an HTTP or HTTPS source URL.")
        page = urlsplit(value)
        if page.scheme not in {"http", "https"} or not page.hostname or page.username is not None:
            raise ValueError("Use an HTTP or HTTPS source URL without credentials.")
        return value

    def as_payload(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, exclude_none=True)

    def web_only(self) -> BrowserSourceRef:
        return BrowserSourceRef(url=self.url, title=self.title, selection=self.selection)


def resolve_library_source(
    service: ResourceService,
    workspace_id: str,
    source: BrowserSourceRef,
) -> BrowserSourceRef:
    """Upgrade a web excerpt, or re-check the precise version carried by a turn."""
    from ..resources.capture import capture_intent_tag, capture_url_key

    web_source = source.web_only()
    url_tag = capture_url_key(source.url)
    selection_tag = capture_intent_tag("selection", source.selection)
    quote = "\n".join(f"> {line}" if line else ">" for line in source.selection.splitlines())
    expected_excerpt = f"## Captured selection\n\n{quote}\n\n"
    for resource in service.repository.list_resources(workspace_id):
        if source.resource_id and source.resource_id != resource.id:
            continue
        if url_tag not in resource.tags or selection_tag not in resource.tags:
            continue
        version = service.version_store.current_version(workspace_id, resource.id)
        if not version or version["content_hash"] != resource.content_hash:
            continue
        if source.resource_id and (
            version["version_id"] != source.version_id or version["content_hash"] != source.content_hash
        ):
            return web_source
        try:
            body = service.read_canonical_text(workspace_id, resource.id)
        except KeyError:  # A deletion may race the preceding resource scan.
            continue
        if body and expected_excerpt in body:
            return BrowserSourceRef(
                url=source.url,
                title=source.title,
                selection=source.selection,
                resourceId=resource.id,
                versionId=version["version_id"],
                contentHash=version["content_hash"],
                location={"heading": "Captured selection"},
            )
    return web_source


def turn_browser_sources(
    service: ResourceService, workspace_id: str, sources: list[BrowserSourceRef],
) -> list[dict[str, object]]:
    verified: list[dict[str, object]] = []
    for source in sources:
        current = (
            resolve_library_source(service, workspace_id, source)
            if source.resource_id else source.web_only()
        )
        provenance = "library" if current.resource_id else (
            "stale_library" if source.resource_id else "temporary_web"
        )
        verified.append({**current.as_payload(), "provenance": provenance})
    return verified
