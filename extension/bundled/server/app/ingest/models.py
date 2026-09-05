from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.resources.models import ResourceChunk, ResourceKind, ResourceRecord


@dataclass(slots=True)
class IngestionRequest:
    source_uri: str
    kind: ResourceKind | None = None
    display_name: str | None = None
    content: str | bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_size: int = 1200
    chunk_overlap: int = 120
    enable_network: bool = False

    @property
    def suffix(self) -> str:
        return Path(self.source_uri).suffix.lower()


@dataclass(slots=True)
class VisionPayload:
    resource_id: str
    source_uri: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class IngestionSummary:
    text_preview: str
    detected_kind: ResourceKind
    extracted_characters: int
    chunk_count: int


@dataclass(slots=True)
class IngestionResult:
    record: ResourceRecord
    chunks: list[ResourceChunk]
    summary: IngestionSummary
    warnings: list[str] = field(default_factory=list)
    vision_payload: VisionPayload | None = None
    source_provenance: dict[str, Any] = field(default_factory=dict)
