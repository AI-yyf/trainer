from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from app.network_fetch import ControlledFetchError, fetch_url
from app.resources.models import IndexStatus, ResourceChunk, ResourceKind, ResourceRecord

from .models import IngestionRequest, IngestionResult, IngestionSummary, VisionPayload

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fitz = None


class ResourceRegistryProtocol(Protocol):
    def register(self, resource: ResourceRecord) -> ResourceRecord:
        ...

    def attach_chunks(
        self,
        resource_id: str,
        chunks: list[ResourceChunk],
        *,
        summary: str | None = None,
        metadata_updates: dict[str, object] | None = None,
    ) -> ResourceRecord:
        ...

    def mark_indexed(self, resource_id: str, *, index_status: IndexStatus) -> ResourceRecord:
        ...

    def clone_resource(self, resource_id: str) -> ResourceRecord:
        ...


class IngestService:
    """Compatibility adapter used by the current runtime wiring."""

    def __init__(self, *, network_fetch_enabled: bool = False) -> None:
        self.network_fetch_enabled = network_fetch_enabled

    def read_source(self, kind: str, source: str, content: str | None = None) -> str:
        request = IngestionRequest(
            source_uri=source,
            kind=ResourceKind(kind) if kind in ResourceKind._value2member_map_ else ResourceKind.UNKNOWN,
            content=content,
            enable_network=False,
        )
        text, _warnings, _provenance = self._extract_text_for_request(request, vision_enabled=False)
        return text

    def describe_source(self, request: IngestionRequest, *, vision_enabled: bool = False) -> tuple[str, list[str]]:
        text, warnings, _provenance = self._extract_text_for_request(request, vision_enabled=vision_enabled)
        return text, warnings

    def describe_source_with_provenance(
        self,
        request: IngestionRequest,
        *,
        vision_enabled: bool = False,
    ) -> tuple[str, list[str], dict[str, object]]:
        return self._extract_text_for_request(request, vision_enabled=vision_enabled)

    def _extract_text_for_request(
        self,
        request: IngestionRequest,
        *,
        vision_enabled: bool,
    ) -> tuple[str, list[str], dict[str, object]]:
        kind = request.kind or ResourceKind.UNKNOWN
        if kind is ResourceKind.PDF or Path(request.source_uri).suffix.lower() == ".pdf":
            text, warnings, provenance = _extract_pdf_text(request)
            return text, warnings, provenance
        if kind is ResourceKind.EPUB or Path(request.source_uri).suffix.lower() == ".epub":
            text, warnings, provenance = _extract_epub_text(request)
            return text, warnings, provenance
        if kind is ResourceKind.IMAGE:
            text, warnings = _extract_image_stub(request, vision_enabled=vision_enabled)
            return text, warnings, {}
        if kind in {ResourceKind.TEXT, ResourceKind.MARKDOWN}:
            text, warnings = _extract_text(request)
            return text, warnings, {}
        if kind is ResourceKind.CODE:
            text, warnings = _extract_code(request)
            return text, warnings, {}
        if kind is ResourceKind.URL:
            return _extract_url(request, network_fetch_enabled=self.network_fetch_enabled)
        text, warnings = _extract_text(request)
        return text, warnings, {}


class ResourceIngestor:
    """Richer ingest orchestration for future core/API integration."""

    def __init__(self, registry: ResourceRegistryProtocol, ingest_service: IngestService | None = None) -> None:
        self._registry = registry
        self._ingest_service = ingest_service or IngestService()

    def ingest(self, request: IngestionRequest, *, vision_enabled: bool = False) -> IngestionResult:
        kind = request.kind or self._detect_kind(request.source_uri)
        resource = self._registry.register(
            ResourceRecord.create(
                kind=kind,
                source_uri=request.source_uri,
                title=request.display_name or Path(request.source_uri).name or request.source_uri,
                metadata=dict(request.metadata),
            )
        )

        materialized_request = IngestionRequest(
            source_uri=request.source_uri,
            kind=kind,
            display_name=request.display_name,
            content=request.content,
            metadata=dict(request.metadata),
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            enable_network=request.enable_network,
        )
        text, warnings, source_provenance = self._ingest_service.describe_source_with_provenance(
            materialized_request,
            vision_enabled=vision_enabled,
        )
        chunks = self._chunk_text(resource.id, text, request.chunk_size, request.chunk_overlap, kind=kind)
        summary = IngestionSummary(
            text_preview=text[:240],
            detected_kind=kind,
            extracted_characters=len(text),
            chunk_count=len(chunks),
        )
        metadata_updates: dict[str, object] = {
            "character_count": len(text),
            "chunk_count": len(chunks),
        }
        if source_provenance.get("paragraph_anchors"):
            metadata_updates["paragraph_anchors"] = source_provenance["paragraph_anchors"]
        if source_provenance.get("content_language"):
            metadata_updates["content_language"] = source_provenance["content_language"]
        if kind is ResourceKind.IMAGE and vision_enabled:
            metadata_updates["vision_ready"] = True
        self._registry.attach_chunks(
            resource.id,
            chunks,
            summary=summary.text_preview,
            metadata_updates=metadata_updates,
        )
        self._registry.mark_indexed(resource.id, index_status=IndexStatus.NOT_INDEXED)

        vision_payload = None
        if kind is ResourceKind.IMAGE and vision_enabled:
            vision_payload = VisionPayload(
                resource_id=resource.id,
                source_uri=request.source_uri,
                prompt="Describe the instructional content of this image for the learner.",
                metadata={"role": "resource_ingest"},
            )

        return IngestionResult(
            record=self._registry.clone_resource(resource.id),
            chunks=chunks,
            summary=summary,
            warnings=warnings,
            vision_payload=vision_payload,
            source_provenance=source_provenance,
        )

    def _detect_kind(self, source_uri: str) -> ResourceKind:
        suffix = Path(source_uri).suffix.lower()
        if suffix == ".pdf":
            return ResourceKind.PDF
        if suffix == ".epub":
            return ResourceKind.EPUB
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            return ResourceKind.IMAGE
        if suffix in {".md", ".markdown"}:
            return ResourceKind.MARKDOWN
        if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml"}:
            return ResourceKind.CODE
        if source_uri.startswith(("http://", "https://")):
            return ResourceKind.URL
        if suffix in {".txt", ".rst"}:
            return ResourceKind.TEXT
        return ResourceKind.UNKNOWN

    def _chunk_text(
        self,
        resource_id: str,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        *,
        kind: ResourceKind,
    ) -> list[ResourceChunk]:
        normalized = text.strip()
        if not normalized:
            return [ResourceChunk.create(resource_id=resource_id, order=0, text="", metadata={"kind": kind.value})]

        if kind is ResourceKind.CODE:
            return _chunk_code(resource_id, normalized, chunk_size)

        chunks: list[ResourceChunk] = []
        start = 0
        order = 0
        step = max(chunk_size - chunk_overlap, 1)
        while start < len(normalized):
            end = min(len(normalized), start + chunk_size)
            window = normalized[start:end]
            chunks.append(
                ResourceChunk.create(
                    resource_id=resource_id,
                    order=order,
                    text=window,
                    metadata={"kind": kind.value},
                )
            )
            order += 1
            start += step
        return chunks


def _build_pdf_paragraph_anchors(pages: list[str]) -> list[dict[str, object]]:
    """Build stable page + char-offset paragraph anchors for PDF (§7.4, §7.8)."""
    anchors: list[dict[str, object]] = []
    for page_no, page_text in enumerate(pages, start=1):
        cursor = 0
        for p_idx, block in enumerate(re.split(r"\n\s*\n", page_text), start=1):
            stripped = block.strip()
            if not stripped:
                continue
            pos = page_text.find(stripped, cursor)
            char_offset = pos if pos >= 0 else cursor
            cursor = max(cursor, char_offset + len(stripped))
            anchors.append(
                {
                    "anchor_id": f"¶p{page_no}.{p_idx}@{char_offset}",
                    "kind": "pdf",
                    "page": page_no,
                    "paragraph_index": p_idx,
                    "char_offset": char_offset,
                    "char_length": len(stripped),
                }
            )
    return anchors


def _extract_pdf_text(request: IngestionRequest) -> tuple[str, list[str], dict[str, object]]:
    warnings: list[str] = []
    if fitz is not None and Path(request.source_uri).exists():
        with fitz.open(request.source_uri) as doc:  # type: ignore[attr-defined]
            pages = [str(page.get_text()) for page in doc]
        anchors = _build_pdf_paragraph_anchors(pages)
        return "\n\n".join(pages).strip(), warnings, {"paragraph_anchors": anchors}
    if isinstance(request.content, bytes):
        warnings.append("PyMuPDF unavailable; falling back to byte decode for PDF content.")
        decoded = request.content.decode("utf-8", errors="ignore")
        anchors = _build_pdf_paragraph_anchors([decoded])
        return decoded, warnings, {"paragraph_anchors": anchors}
    warnings.append("PDF ingest ran in stub mode because PyMuPDF was unavailable or the file was missing.")
    text = str(request.content or "")
    anchors = _build_pdf_paragraph_anchors([text]) if text.strip() else []
    return text, warnings, {"paragraph_anchors": anchors}


def _extract_epub_text(request: IngestionRequest) -> tuple[str, list[str], dict[str, object]]:
    """Extract EPUB text and build stable spine + element-path paragraph anchors (P1 #16, §7.4, §7.8)."""
    import io
    import posixpath
    import xml.etree.ElementTree as ET
    import zipfile

    warnings: list[str] = []
    archive_source: str | io.BytesIO | None = None
    if Path(request.source_uri).exists():
        archive_source = request.source_uri
    elif isinstance(request.content, bytes):
        archive_source = io.BytesIO(request.content)
    elif isinstance(request.content, str) and request.content.strip():
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", request.content) if p.strip()]
        anchors = [
            {
                "anchor_id": f"¶spine0/body/p[{idx}]@0",
                "kind": "epub",
                "spine_index": 0,
                "spine_id": "inline",
                "element_path": f"/body/p[{idx}]",
                "char_offset": 0,
                "char_length": len(p),
            }
            for idx, p in enumerate(paragraphs, start=1)
        ]
        return request.content.strip(), warnings, {"paragraph_anchors": anchors}

    if archive_source is None:
        warnings.append("EPUB resource had no readable archive path or inline content.")
        return "", warnings, {}

    try:
        with zipfile.ZipFile(archive_source) as archive:
            container_xml = archive.read("META-INF/container.xml")
            container_root = ET.fromstring(container_xml)
            opf_path = ""
            for elem in container_root.iter():
                if elem.tag.split("}")[-1] == "rootfile":
                    opf_path = str(elem.attrib.get("full-path") or "").strip()
                    if opf_path:
                        break
            if not opf_path:
                warnings.append("EPUB container.xml did not declare a rootfile.")
                return "", warnings, {}
            opf_root = ET.fromstring(archive.read(opf_path))
            manifest: dict[str, str] = {}
            spine: list[str] = []
            content_language: str | None = None
            for elem in opf_root.iter():
                local = elem.tag.split("}")[-1]
                if local == "language" and content_language is None:
                    lang_text = "".join(elem.itertext()).strip()
                    if lang_text:
                        content_language = lang_text
                elif local == "item":
                    item_id = str(elem.attrib.get("id") or "").strip()
                    href = str(elem.attrib.get("href") or "").strip()
                    if item_id and href:
                        manifest[item_id] = href
                elif local == "itemref":
                    idref = str(elem.attrib.get("idref") or "").strip()
                    if idref:
                        spine.append(idref)

            opf_dir = posixpath.dirname(opf_path)
            extracted_paragraphs: list[str] = []
            anchors: list[dict[str, object]] = []
            for spine_idx, idref in enumerate(spine):
                href = manifest.get(idref)
                if not href:
                    continue
                chapter_path = posixpath.normpath(posixpath.join(opf_dir, href))
                try:
                    raw_html = archive.read(chapter_path).decode("utf-8", errors="ignore")
                except KeyError:
                    continue
                p_index = 0
                try:
                    chapter_root = ET.fromstring(raw_html)
                    for elem in chapter_root.iter():
                        tag = elem.tag.split("}")[-1].lower()
                        if tag in {"p", "h1", "h2", "h3", "h4", "blockquote", "li"}:
                            text_val = " ".join("".join(elem.itertext()).split()).strip()
                            if not text_val:
                                continue
                            p_index += 1
                            element_path = f"/body/{tag}[{p_index}]"
                            extracted_paragraphs.append(text_val)
                            anchors.append(
                                {
                                    "anchor_id": f"¶spine:{idref}:{element_path}",
                                    "kind": "epub",
                                    "spine_index": spine_idx,
                                    "spine_id": idref,
                                    "href": chapter_path,
                                    "element_path": element_path,
                                    "char_offset": 0,
                                    "char_length": len(text_val),
                                }
                            )
                except Exception:
                    # Fallback regex paragraph extraction if XHTML isn't strict XML
                    for block in re.findall(r"<(?:p|h[1-6]|blockquote)[^>]*>(.*?)</(?:p|h[1-6]|blockquote)>", raw_html, flags=re.I | re.S):
                        cleaned = re.sub(r"<[^>]+>", " ", block)
                        cleaned = " ".join(cleaned.split()).strip()
                        if not cleaned:
                            continue
                        p_index += 1
                        element_path = f"/body/p[{p_index}]"
                        extracted_paragraphs.append(cleaned)
                        anchors.append(
                            {
                                "anchor_id": f"¶spine:{idref}:{element_path}",
                                "kind": "epub",
                                "spine_index": spine_idx,
                                "spine_id": idref,
                                "href": chapter_path,
                                "element_path": element_path,
                                "char_offset": 0,
                                "char_length": len(cleaned),
                            }
                        )
            provenance: dict[str, object] = {"paragraph_anchors": anchors}
            if content_language:
                provenance["content_language"] = content_language
            return "\n\n".join(extracted_paragraphs).strip(), warnings, provenance
    except Exception as exc:
        warnings.append(f"EPUB parsing failed: {exc}")
        return "", warnings, {}


def _extract_image_stub(request: IngestionRequest, *, vision_enabled: bool) -> tuple[str, list[str]]:
    if vision_enabled:
        return (
            f"Image resource placeholder for {request.source_uri}. The provider can inspect this asset in a later multimodal step.",
            [],
        )
    return (
        f"Image resource metadata only for {request.source_uri}. Vision is disabled, so OCR and multimodal analysis were skipped.",
        ["Vision capability disabled; stored only image metadata and a placeholder summary."],
    )


def _extract_text(request: IngestionRequest) -> tuple[str, list[str]]:
    if isinstance(request.content, bytes):
        return request.content.decode("utf-8", errors="ignore"), []
    if request.content is not None:
        return request.content, []
    if Path(request.source_uri).exists():
        return Path(request.source_uri).read_text(encoding="utf-8"), []
    return "", ["Text resource had no inline content and no readable file path."]


def _extract_code(request: IngestionRequest) -> tuple[str, list[str]]:
    return _extract_text(request)


def _extract_url(
    request: IngestionRequest,
    *,
    network_fetch_enabled: bool,
) -> tuple[str, list[str], dict[str, object]]:
    if isinstance(request.content, str):
        return request.content, [], {"status": "provided"}
    network_enabled = bool(request.enable_network) and network_fetch_enabled
    if not network_enabled:
        return (
            f"URL resource placeholder for {request.source_uri}. Network fetch is disabled until a caller opts in.",
            ["URL fetch skipped because network fetch is not enabled by both request and configuration."],
            {"status": "network_disabled", "reason_code": "network_disabled"},
        )
    try:
        response = fetch_url(
            request.source_uri,
            network_enabled=network_enabled,
        )
    except ControlledFetchError as exc:
        if exc.code in {
            "unsupported_scheme",
            "userinfo_not_allowed",
            "missing_host",
            "invalid_host",
            "invalid_port",
            "invalid_url",
            "invalid_resolution",
            "dns_no_addresses",
            "dns_too_many_addresses",
            "blocked_address",
            "non_standard_port",
            "redirect_missing_location",
        }:
            return (
                f"URL fetch blocked for {request.source_uri}",
                [f"URL fetch blocked: {exc.code}."],
                {"status": "blocked", "reason_code": exc.code},
            )
        return (
            f"URL fetch failed for {request.source_uri}",
            [f"URL fetch failed: {exc.code}."],
            {"status": "failed", "reason_code": exc.code},
        )
    raw_text = response.body.decode("utf-8", errors="ignore")
    extracted = _html_to_text(raw_text)
    return (
        extracted or raw_text,
        [],
        {
            "status": "fetched",
            "final_url": response.final_url,
            "fetched_at": response.fetched_at,
            "content_type": response.content_type,
        },
    )


def _html_to_text(raw: str) -> str:
    without_script = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", without_script)
    compact = re.sub(r"\\s+", " ", no_tags).strip()
    return compact[:8000]


def _chunk_code(resource_id: str, text: str, chunk_size: int) -> list[ResourceChunk]:
    lines = text.splitlines()
    if not lines:
        return [ResourceChunk.create(resource_id=resource_id, order=0, text="", metadata={"kind": ResourceKind.CODE.value})]
    chunks: list[ResourceChunk] = []
    bucket: list[str] = []
    start_line = 1
    current_len = 0
    order = 0
    for line_no, line in enumerate(lines, start=1):
        bucket.append(line)
        current_len += len(line) + 1
        if current_len >= chunk_size:
            chunks.append(
                ResourceChunk.create(
                    resource_id=resource_id,
                    order=order,
                    text="\n".join(bucket),
                    start_line=start_line,
                    end_line=line_no,
                    metadata={"kind": ResourceKind.CODE.value},
                )
            )
            order += 1
            bucket = []
            start_line = line_no + 1
            current_len = 0
    if bucket:
        chunks.append(
            ResourceChunk.create(
                resource_id=resource_id,
                order=order,
                text="\n".join(bucket),
                start_line=start_line,
                end_line=len(lines),
                metadata={"kind": ResourceKind.CODE.value},
            )
        )
    return chunks
