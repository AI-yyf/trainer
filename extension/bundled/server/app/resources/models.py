from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResourceKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"
    TEXT = "text"
    MARKDOWN = "markdown"
    CODE = "code"
    URL = "url"
    UNKNOWN = "unknown"


class IngestStatus(StrEnum):
    PENDING = "pending"
    INGESTED = "ingested"
    FAILED = "failed"


class IndexStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(slots=True)
class ResourceRecord:
    id: str
    kind: ResourceKind
    source_uri: str
    title: str
    media_type: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ingest_status: IngestStatus = IngestStatus.PENDING
    index_status: IndexStatus = IndexStatus.NOT_INDEXED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        kind: ResourceKind,
        source_uri: str,
        title: str,
        media_type: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ResourceRecord":
        return cls(
            id=f"res_{uuid4().hex}",
            kind=kind,
            source_uri=source_uri,
            title=title,
            media_type=media_type,
            summary=summary,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class ResourceChunk:
    resource_id: str
    chunk_id: str
    text: str
    order: int
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        resource_id: str,
        order: int,
        text: str,
        start_line: int | None = None,
        end_line: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ResourceChunk":
        return cls(
            resource_id=resource_id,
            chunk_id=f"chunk_{uuid4().hex}",
            text=text,
            order=order,
            start_line=start_line,
            end_line=end_line,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class ResourceUploadResponse:
    resource: ResourceRecord
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResourceIndexResponse:
    resource: ResourceRecord
    chunk_count: int
    warnings: list[str] = field(default_factory=list)
