"""Canonical Markdown documents for imported sources.

Every document resource (DOCX / PPTX / PDF / HTML / Markdown / text / code /
image) is digested into one stable Markdown document with YAML front matter.
The original file is kept untouched; search, reading, citations, training
cards and agent context consume the Markdown body.

The parsers here are intentionally self-contained: OpenXML packages are read
with ``zipfile`` + ``ElementTree`` so DOCX/PPTX conversion does not depend on
an optional third-party converter being present at runtime, and PDF text uses
PyMuPDF when available.  Every parser reports what it could not do in
``warnings`` instead of fabricating content.
"""

from __future__ import annotations

import html as html_module
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from .ocr import ocr_image_bytes

CANONICAL_PARSER_VERSION = "1"

SOURCE_TYPE_BY_SUFFIX: dict[str, str] = {
    ".docx": "docx",
    ".docm": "docx",
    ".pptx": "pptx",
    ".pptm": "pptx",
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".mkd": "markdown",
    ".txt": "text",
    ".text": "text",
    ".rst": "text",
    ".log": "text",
    ".csv": "text",
    ".tsv": "text",
    ".py": "code",
    ".ts": "code",
    ".tsx": "code",
    ".js": "code",
    ".jsx": "code",
    ".mjs": "code",
    ".cjs": "code",
    ".json": "code",
    ".yaml": "code",
    ".yml": "code",
    ".toml": "code",
    ".ini": "code",
    ".cfg": "code",
    ".sh": "code",
    ".ps1": "code",
    ".rs": "code",
    ".go": "code",
    ".java": "code",
    ".kt": "code",
    ".c": "code",
    ".h": "code",
    ".cpp": "code",
    ".hpp": "code",
    ".cs": "code",
    ".rb": "code",
    ".php": "code",
    ".swift": "code",
    ".sql": "code",
    ".css": "code",
    ".scss": "code",
    ".vue": "code",
    ".svelte": "code",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".svg": "image",
    ".tif": "image",
    ".tiff": "image",
}

PARSER_BY_SOURCE_TYPE: dict[str, str] = {
    "docx": "docx-v1",
    "pptx": "pptx-v1",
    "pdf": "pdf-v1",
    "html": "html-v1",
    "markdown": "markdown-v1",
    "text": "text-v1",
    "code": "text-v1",
    "image": "image-v1",
}

MIME_BY_SUFFIX: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".docm": "application/vnd.ms-word.document.macroEnabled.12",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".rst": "text/x-rst",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

LEGACY_OFFICE_SUFFIXES = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}

FRONT_MATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n)*", re.DOTALL)


class CanonicalParseError(ValueError):
    """A source could not be digested into a usable Markdown document."""

    def __init__(self, message: str, *, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.warnings = list(warnings or [])


@dataclass(slots=True)
class CanonicalAsset:
    """One binary asset extracted from the source and stored next to the Markdown."""

    filename: str
    data: bytes
    source_part: str = ""
    media_type: str = ""


@dataclass(slots=True)
class DocumentAnchor:
    """A citable location inside the Markdown body."""

    kind: str  # "page" | "slide" | "heading"
    index: int
    label: str
    line: int  # 1-based line inside the Markdown body (excluding front matter)

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "index": self.index, "line": self.line}
        if self.label:
            payload["label"] = self.label
        return payload


@dataclass(slots=True)
class CanonicalDocument:
    """The canonical Markdown projection of one source file."""

    resource_id: str
    source_type: str
    parser: str
    parser_version: str
    body: str
    original_filename: str
    original_mime: str
    original_size: int
    content_hash: str
    imported_at: str
    version_id: str = ""
    source_url: str = ""
    page_count: int | None = None
    slide_count: int | None = None
    warnings: list[str] = field(default_factory=list)
    assets: list[CanonicalAsset] = field(default_factory=list)
    anchors: list[DocumentAnchor] = field(default_factory=list)

    def front_matter(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "resource_id": self.resource_id,
            "source_type": self.source_type,
            "original_filename": self.original_filename,
            "original_mime": self.original_mime,
            "original_size": self.original_size,
            "content_hash": self.content_hash,
            "version_id": self.version_id,
            "imported_at": self.imported_at,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "warnings": list(self.warnings),
        }
        if self.source_url:
            payload["source_url"] = self.source_url
        if self.page_count is not None:
            payload["page_count"] = self.page_count
        if self.slide_count is not None:
            payload["slide_count"] = self.slide_count
        if self.assets:
            payload["asset_count"] = len(self.assets)
        if self.anchors:
            payload["anchors"] = [anchor.as_payload() for anchor in self.anchors]
        return payload

    def render(self) -> str:
        return render_front_matter(self.front_matter()) + self.body.rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Front matter
# --------------------------------------------------------------------------- #


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text and re.fullmatch(r"[A-Za-z0-9_./:@+\- ]+", text) and text == text.strip():
        if text.lower() not in {"true", "false", "null", "yes", "no", "on", "off"}:
            if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
                return text
    return json.dumps(text, ensure_ascii=False)


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{{}}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_lines(item, indent + 2))
            elif isinstance(item, list) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_lines(item, indent + 2))
            elif isinstance(item, dict):
                lines.append(f"{pad}{key}: {{}}")
            elif isinstance(item, list):
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{pad}- {{}}")
                    continue
                first = True
                for key, child in item.items():
                    prefix = f"{pad}- " if first else f"{pad}  "
                    if isinstance(child, (dict, list)) and child:
                        lines.append(f"{prefix}{key}:")
                        lines.extend(_yaml_lines(child, indent + 4))
                    elif isinstance(child, dict):
                        lines.append(f"{prefix}{key}: {{}}")
                    elif isinstance(child, list):
                        lines.append(f"{prefix}{key}: []")
                    else:
                        lines.append(f"{prefix}{key}: {_yaml_scalar(child)}")
                    first = False
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [f"{pad}{_yaml_scalar(value)}"]


def render_front_matter(payload: dict[str, Any]) -> str:
    return "---\n" + "\n".join(_yaml_lines(payload)) + "\n---\n\n"


def strip_front_matter(markdown: str) -> str:
    match = FRONT_MATTER_PATTERN.match(markdown)
    if match is None:
        return markdown
    return markdown[match.end() :]


def read_front_matter(markdown: str) -> dict[str, Any]:
    """Parse the small YAML subset emitted by :func:`render_front_matter`.

    This intentionally only understands the front matter this module writes
    (scalars, flow lists, nested maps and lists of maps); it is not a general
    YAML parser.
    """

    match = FRONT_MATTER_PATTERN.match(markdown)
    if match is None:
        return {}
    lines = [line for line in match.group(1).splitlines() if line.strip()]
    node, _index = _parse_yaml_node(lines, 0, 0)
    return node if isinstance(node, dict) else {}


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_yaml_node(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    if lines[index].strip().startswith("- "):
        items: list[Any] = []
        while index < len(lines):
            line = lines[index]
            if _indent_of(line) != indent or not line.strip().startswith("- "):
                break
            rest = line.strip()[2:].strip()
            index += 1
            if not rest:
                node, index = _parse_yaml_node(lines, index, indent + 2)
                items.append(node)
                continue
            if ":" in rest and not rest.startswith('"'):
                key, _sep, value = rest.partition(":")
                item: dict[str, Any] = {
                    key.strip(): _parse_scalar(value.strip()) if value.strip() else {}
                }
                while index < len(lines) and _indent_of(lines[index]) == indent + 2:
                    child_line = lines[index].strip()
                    if child_line.startswith("- "):
                        break
                    child_key, sep, child_value = child_line.partition(":")
                    if not sep:
                        index += 1
                        continue
                    if child_value.strip():
                        item[child_key.strip()] = _parse_scalar(child_value.strip())
                        index += 1
                    else:
                        index += 1
                        node, index = _parse_yaml_node(lines, index, indent + 4)
                        item[child_key.strip()] = node
                items.append(item)
                continue
            items.append(_parse_scalar(rest))
        return items, index
    result: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if _indent_of(line) != indent:
            index += 1
            continue
        content = line.strip()
        if content.startswith("- "):
            break
        key, sep, value = content.partition(":")
        if not sep:
            index += 1
            continue
        key = key.strip()
        index += 1
        if value.strip():
            result[key] = _parse_scalar(value.strip())
        else:
            node, index = _parse_yaml_node(lines, index, indent + 2)
            result[key] = node
    return result, index


def _parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value.strip('"')
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def source_type_for_path(path: str | Path) -> str | None:
    return SOURCE_TYPE_BY_SUFFIX.get(Path(path).suffix.lower())


def canonicalizable(path: str | Path) -> bool:
    return source_type_for_path(path) is not None


def build_canonical_document(
    path: str | Path,
    *,
    resource_id: str,
    imported_at: str | None = None,
    version_id: str = "",
    content_hash: str = "",
    source_url: str = "",
    original_name: str | None = None,
) -> CanonicalDocument:
    """Digest one local source file into its canonical Markdown document."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in LEGACY_OFFICE_SUFFIXES:
        replacement = LEGACY_OFFICE_SUFFIXES[suffix]
        raise CanonicalParseError(
            f"Legacy {suffix} files are not supported; save the file as {replacement} and import it again."
        )
    source_type = SOURCE_TYPE_BY_SUFFIX.get(suffix)
    if source_type is None:
        raise CanonicalParseError(f"Unsupported document type: {suffix or source.name}")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise CanonicalParseError(f"Could not read the source file: {exc}") from exc

    imported = imported_at or datetime.now(timezone.utc).isoformat()
    filename = _safe_original_name(original_name or source.name)

    if source_type == "docx":
        body, warnings, assets, page_count, slide_count = _parse_docx(raw)
    elif source_type == "pptx":
        body, warnings, assets, page_count, slide_count = _parse_pptx(raw)
    elif source_type == "pdf":
        body, warnings, assets, page_count, slide_count = _parse_pdf(source, raw)
    elif source_type == "html":
        body, warnings, assets, page_count, slide_count = _parse_html(raw, source_url or source.as_uri())
    elif source_type == "image":
        body, warnings, assets, page_count, slide_count = _parse_image(raw, filename)
    elif source_type == "markdown":
        body, warnings, assets, page_count, slide_count = _parse_text_like(raw, filename, markdown=True)
    else:
        body, warnings, assets, page_count, slide_count = _parse_text_like(raw, filename, markdown=False)

    anchors = anchors_for_body(body, source_type)

    if not body.strip():
        detail = warnings[0] if warnings else "The parser produced no readable text."
        raise CanonicalParseError(f"Could not extract text from {filename}: {detail}", warnings=warnings)

    return CanonicalDocument(
        resource_id=resource_id,
        source_type=source_type,
        parser=PARSER_BY_SOURCE_TYPE[source_type],
        parser_version=CANONICAL_PARSER_VERSION,
        body=body,
        original_filename=filename,
        original_mime=MIME_BY_SUFFIX.get(suffix, "application/octet-stream"),
        original_size=len(raw),
        content_hash=content_hash or f"sha256:{_sha256_hex(raw)}",
        imported_at=imported,
        version_id=version_id,
        source_url=source_url,
        page_count=page_count,
        slide_count=slide_count,
        warnings=warnings,
        assets=assets,
        anchors=anchors,
    )


def build_canonical_from_text(
    text: str,
    *,
    resource_id: str,
    original_filename: str,
    source_url: str = "",
    source_type: str = "html",
    imported_at: str | None = None,
    version_id: str = "",
    content_hash: str = "",
    warnings: list[str] | None = None,
) -> CanonicalDocument:
    """Build a canonical document from already extracted text (URL captures)."""

    body = text.strip()
    if body and not _looks_like_markdown_heading(body):
        body = f"# {original_filename.rsplit('.', 1)[0]}\n\n{body}"
    if not body:
        raise CanonicalParseError(
            "The source produced no readable text.",
            warnings=list(warnings or []),
        )
    filename = _safe_original_name(original_filename)
    return CanonicalDocument(
        resource_id=resource_id,
        source_type=source_type,
        parser=PARSER_BY_SOURCE_TYPE.get(source_type, "html-v1"),
        parser_version=CANONICAL_PARSER_VERSION,
        body=body,
        original_filename=filename,
        original_mime=MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), "text/markdown"),
        original_size=len(body.encode("utf-8")),
        content_hash=content_hash or f"sha256:{_sha256_hex(body.encode('utf-8'))}",
        imported_at=imported_at or datetime.now(timezone.utc).isoformat(),
        version_id=version_id,
        source_url=source_url,
        warnings=list(warnings or []),
        anchors=anchors_for_body(body, source_type),
    )


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_V = "{urn:schemas-microsoft-com:vml}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _parse_docx(
    raw: bytes,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    import io
    import xml.etree.ElementTree as ET

    warnings: list[str] = []
    assets: list[CanonicalAsset] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise CanonicalParseError("The .docx package is corrupted and could not be opened.") from exc

    with archive:
        document_xml = _read_zip_part(archive, "word/document.xml")
        if document_xml is None:
            raise CanonicalParseError("The .docx package has no word/document.xml part.")
        rels = _read_relationships(archive, "word/_rels/document.xml.rels")
        footnotes = _docx_footnotes(archive)
        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as exc:
            raise CanonicalParseError("The .docx document body is not valid XML.") from exc

        body_node = root.find(f"{_W}body")
        if body_node is None:
            raise CanonicalParseError("The .docx document has no body.")

        blocks: list[str] = []
        image_counter = 0
        footnote_refs: list[str] = []
        for child in list(body_node):
            if child.tag == f"{_W}p":
                text, images, refs = _docx_paragraph(child, rels)
                footnote_refs.extend(refs)
                style = _docx_paragraph_style(child)
                level = _heading_level(style)
                stripped = text.strip()
                if level and stripped:
                    blocks.append(f"{'#' * level} {stripped}")
                elif stripped:
                    blocks.append(stripped)
                elif blocks and blocks[-1] != "":
                    blocks.append("")
                for image in images:
                    image_counter += 1
                    asset = _docx_image_asset(archive, image, image_counter)
                    if asset is None:
                        warnings.append(f"Could not extract an embedded image ({image or 'unknown relationship'}).")
                        continue
                    assets.append(asset)
                    blocks.append(f"![{Path(asset.filename).stem}](assets/{asset.filename})")
            elif child.tag == f"{_W}tbl":
                table = _docx_table(child, rels)
                if table:
                    blocks.append(table)
        if footnote_refs:
            blocks.append("## Footnotes")
            for ref in dict.fromkeys(footnote_refs):
                text = footnotes.get(ref, "").strip()
                if text:
                    blocks.append(f"[^{ref}]: {text}")

        body = _join_blocks(blocks)
        if not body.strip():
            warnings.append("The document contains no paragraph text.")
        if any(not footnote_refs and note for note in footnotes.values()):
            warnings.append("Footnotes were found but not referenced from the document body.")
        page_count = _docx_page_count(archive)
        return body, warnings, assets, page_count, None


def _docx_paragraph(
    paragraph: Any,
    rels: dict[str, str],
) -> tuple[str, list[str], list[str]]:
    parts: list[str] = []
    images: list[str] = []
    footnote_refs: list[str] = []

    def walk(node: Any) -> None:
        for child in node:
            tag = child.tag
            if tag == f"{_W}r":
                for sub in child:
                    if sub.tag == f"{_W}t":
                        parts.append(sub.text or "")
                    elif sub.tag == f"{_W}tab":
                        parts.append("\t")
                    elif sub.tag in {f"{_W}br", f"{_W}cr"}:
                        parts.append("  \n")
                for sub in child.iter(f"{_W}footnoteReference"):
                    ref = str(sub.get(f"{_W}id") or "").strip()
                    if ref:
                        footnote_refs.append(ref)
                        parts.append(f"[^{ref}]")
                for drawing in child:
                    if drawing.tag in {f"{_W}drawing", f"{_W}pict"}:
                        for blip in drawing.iter(f"{_A}blip"):
                            rel_id = str(blip.get(f"{_R}embed") or blip.get(f"{_R}link") or "").strip()
                            if rel_id:
                                images.append(rel_id)
                        for image_data in drawing.iter(f"{_V}imagedata"):
                            rel_id = str(image_data.get(f"{_R}id") or "").strip()
                            if rel_id:
                                images.append(rel_id)
            elif tag == f"{_W}hyperlink":
                label = "".join(str(item.text or "") for item in child.iter(f"{_W}t")).strip()
                rel_id = str(child.get(f"{_R}id") or "").strip()
                target = rels.get(rel_id, "")
                if label:
                    parts.append(f"[{label}]({target})" if target else label)
            elif tag in {f"{_W}drawing", f"{_W}pict"}:
                for blip in child.iter(f"{_A}blip"):
                    rel_id = str(blip.get(f"{_R}embed") or blip.get(f"{_R}link") or "").strip()
                    if rel_id:
                        images.append(rel_id)
                for image_data in child.iter(f"{_V}imagedata"):
                    rel_id = str(image_data.get(f"{_R}id") or "").strip()
                    if rel_id:
                        images.append(rel_id)
            elif tag in {f"{_W}ins", f"{_W}smartTag", f"{_W}sdt", f"{_W}sdtContent"}:
                walk(child)

    walk(paragraph)
    return "".join(parts), images, footnote_refs


def _docx_paragraph_style(paragraph: Any) -> str:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return ""
    return str(style.get(f"{_W}val") or "")


def _heading_level(style: str) -> int:
    normalized = style.strip().lower().replace(" ", "")
    if not normalized:
        return 0
    if normalized in {"title"}:
        return 1
    match = re.fullmatch(r"heading(\d+)", normalized)
    if match:
        # The Word "Title" style is the document title (H1), so section
        # headings shift down one level and the hierarchy stays intact.
        return max(1, min(6, int(match.group(1)) + 1))
    match = re.fullmatch(r"h(\d+)", normalized)
    if match:
        return max(1, min(6, int(match.group(1))))
    return 0


def _docx_table(table: Any, rels: dict[str, str]) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{_W}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{_W}tc"):
            texts: list[str] = []
            for paragraph in cell.findall(f"{_W}p"):
                text, _images, _refs = _docx_paragraph(paragraph, rels)
                if text.strip():
                    texts.append(text.strip())
            cells.append(" ".join(texts).replace("|", "\\|"))
        if cells:
            rows.append(cells)
    return _markdown_table(rows)


def _docx_footnotes(archive: zipfile.ZipFile) -> dict[str, str]:
    raw = _read_zip_part(archive, "word/footnotes.xml")
    if raw is None:
        return {}
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    notes: dict[str, str] = {}
    for note in root.findall(f"{_W}footnote"):
        note_id = str(note.get(f"{_W}id") or "").strip()
        if not note_id or note_id.startswith("-"):
            continue
        text = " ".join(
            "".join(str(item.text or "") for item in paragraph.iter(f"{_W}t")).strip()
            for paragraph in note.findall(f"{_W}p")
        ).strip()
        if text:
            notes[note_id] = text
    return notes


def _docx_image_asset(archive: zipfile.ZipFile, rel_id: str, counter: int) -> CanonicalAsset | None:
    # ``rel_id`` is resolved through the relationships map by the caller's
    # archive read; DOCX relationships target ``media/*`` inside the package.
    rels = _read_relationships(archive, "word/_rels/document.xml.rels")
    target = rels.get(rel_id, "")
    if not target:
        return None
    part = posixpath.normpath(posixpath.join("word", target))
    data = _read_zip_part(archive, part)
    if data is None:
        return None
    suffix = Path(part).suffix.lower() or ".bin"
    filename = f"docx-image-{counter:03d}{suffix}"
    return CanonicalAsset(filename=filename, data=data, source_part=part, media_type=MIME_BY_SUFFIX.get(suffix, ""))


def _docx_page_count(archive: zipfile.ZipFile) -> int | None:
    raw = _read_zip_part(archive, "docProps/app.xml")
    if raw is None:
        return None
    match = re.search(rb"<Pages>(\d+)</Pages>", raw)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------- #
# PPTX
# --------------------------------------------------------------------------- #

_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _parse_pptx(
    raw: bytes,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    import io
    import xml.etree.ElementTree as ET

    warnings: list[str] = []
    assets: list[CanonicalAsset] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise CanonicalParseError("The .pptx package is corrupted and could not be opened.") from exc

    with archive:
        slide_parts = _pptx_slide_parts(archive)
        if not slide_parts:
            raise CanonicalParseError("The .pptx package contains no slides.")
        blocks: list[str] = []
        image_counter = 0
        for slide_number, part in enumerate(slide_parts, start=1):
            data = _read_zip_part(archive, part)
            if data is None:
                warnings.append(f"Slide {slide_number}: package part is missing.")
                continue
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                warnings.append(f"Slide {slide_number}: not valid XML; skipped.")
                continue
            rels = _read_relationships(
                archive,
                posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"),
            )
            title, body_blocks, image_rels, has_table = _pptx_slide_content(root)
            hidden = str(root.get("show") or "").strip() == "0"
            heading = f"## Slide {slide_number}" + (f" — {title}" if title else "")
            blocks.append(heading)
            if hidden:
                blocks.append("<!-- slide-hidden: true -->")
                warnings.append(f"Slide {slide_number} is hidden in the presentation.")
            blocks.extend(body_blocks)
            if not body_blocks and not has_table:
                warnings.append(f"Slide {slide_number}: no body text (it may be image-only).")
            for rel_id in image_rels:
                target = rels.get(rel_id, "")
                asset = _pptx_image_asset(archive, part, target, image_counter + 1)
                image_counter += 1
                if asset is None:
                    warnings.append(f"Slide {slide_number}: an embedded image could not be extracted.")
                    continue
                assets.append(asset)
                blocks.append(f"![{Path(asset.filename).stem}](assets/{asset.filename})")
            notes = _pptx_speaker_notes(archive, part, rels)
            if notes:
                blocks.append("#### Speaker notes")
                blocks.extend(notes)
            blocks.append("")

        body = _join_blocks(blocks)
        return body, _dedupe(warnings), assets, None, len(slide_parts)


def _pptx_slide_parts(archive: zipfile.ZipFile) -> list[str]:
    parts: list[tuple[int, str]] = []
    for name in archive.namelist():
        match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
        if match:
            parts.append((int(match.group(1)), name))
    parts.sort(key=lambda item: item[0])
    return [name for _number, name in parts]


def _pptx_slide_content(root: Any) -> tuple[str, list[str], list[str], bool]:
    title = ""
    blocks: list[str] = []
    image_rels: list[str] = []
    has_table = False
    sp_tree = root.find(f"{_P}cSld/{_P}spTree")
    if sp_tree is None:
        return title, blocks, image_rels, has_table
    for shape in list(sp_tree):
        if shape.tag == f"{_P}sp":
            placeholder = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
            placeholder_type = str(placeholder.get("type") or "") if placeholder is not None else ""
            text_body = shape.find(f"{_P}txBody")
            paragraphs = _pptx_paragraphs(text_body)
            if placeholder_type in {"title", "ctrTitle"} and not title:
                title = " ".join(paragraphs).strip()
                continue
            if placeholder_type in {"sldNum", "dt", "ftr"}:
                continue
            blocks.extend(paragraphs)
        elif shape.tag == f"{_P}graphicFrame":
            table = shape.find(f".//{_A}tbl")
            if table is not None:
                has_table = True
                blocks.append(_pptx_table(table))
        elif shape.tag == f"{_P}pic":
            rel_id = _pptx_blip_rel_id(shape)
            if rel_id:
                image_rels.append(rel_id)
        elif shape.tag == f"{_P}grpSp":
            for inner in shape.iter():
                if inner.tag == f"{_P}pic":
                    rel_id = _pptx_blip_rel_id(inner)
                    if rel_id:
                        image_rels.append(rel_id)
    return title, blocks, image_rels, has_table


def _pptx_blip_rel_id(node: Any) -> str:
    blip = node.find(f"{_P}blipFill/{_A}blip")
    if blip is None:
        blip = node.find(f".//{_A}blip")
    if blip is None:
        return ""
    return str(blip.get(f"{_R}embed") or blip.get(f"{_R}link") or "").strip()


def _pptx_paragraphs(text_body: Any) -> list[str]:
    if text_body is None:
        return []
    paragraphs: list[str] = []
    for paragraph in text_body.findall(f"{_A}p"):
        text = _collection_text(paragraph)
        if not text.strip():
            paragraphs.append("")
            continue
        level = 0
        properties = paragraph.find(f"{_A}pPr")
        if properties is not None:
            raw_level = properties.get("lvl")
            if raw_level is None:
                level_node = properties.find(f"{_A}lvl")
                raw_level = (
                    (level_node.get("val") or level_node.text)
                    if level_node is not None
                    else None
                )
            try:
                level = int(raw_level or 0)
            except (TypeError, ValueError):
                level = 0
        bullet = _pptx_has_bullet(paragraph)
        if bullet:
            paragraphs.append(f"{'  ' * max(0, level)}- {text.strip()}")
        else:
            paragraphs.append(text.strip())
    while paragraphs and paragraphs[-1] == "":
        paragraphs.pop()
    return paragraphs


def _pptx_has_bullet(paragraph: Any) -> bool:
    properties = paragraph.find(f"{_A}pPr")
    if properties is None:
        return False
    if properties.find(f"{_A}buNone") is not None:
        return False
    return any(
        properties.find(tag) is not None
        for tag in (f"{_A}buChar", f"{_A}buAutoNum", f"{_A}buBlip")
    )


def _collection_text(node: Any) -> str:
    parts: list[str] = []
    for child in node.iter():
        if child.tag == f"{_A}t":
            parts.append(child.text or "")
        elif child.tag == f"{_A}br":
            parts.append("  \n")
        elif child.tag == f"{_A}tab":
            parts.append("\t")
    return "".join(parts)


def _pptx_table(table: Any) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{_A}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{_A}tc"):
            text = _collection_text(cell).strip()
            cells.append(" ".join(text.split()).replace("|", "\\|"))
        if cells:
            rows.append(cells)
    return _markdown_table(rows)


def _pptx_speaker_notes(archive: zipfile.ZipFile, slide_part: str, rels: dict[str, str]) -> list[str]:
    notes_part = ""
    for _rel_id, target in rels.items():
        if target and "notesSlide" in target:
            notes_part = posixpath.normpath(posixpath.join(posixpath.dirname(slide_part), target))
            break
    if not notes_part:
        return []
    data = _read_zip_part(archive, notes_part)
    if data is None:
        return []
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    notes: list[str] = []
    for shape in root.iter(f"{_P}sp"):
        placeholder = shape.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
        placeholder_type = str(placeholder.get("type") or "") if placeholder is not None else ""
        if placeholder_type in {"sldNum", "sldImg", "hdr", "ftr", "dt"}:
            continue
        paragraphs = _pptx_paragraphs(shape.find(f"{_P}txBody"))
        for paragraph in paragraphs:
            if paragraph.strip():
                notes.append(paragraph.strip())
    return notes


def _pptx_image_asset(
    archive: zipfile.ZipFile,
    slide_part: str,
    target: str,
    counter: int,
) -> CanonicalAsset | None:
    if not target:
        return None
    part = posixpath.normpath(posixpath.join(posixpath.dirname(slide_part), target))
    data = _read_zip_part(archive, part)
    if data is None:
        return None
    suffix = Path(part).suffix.lower() or ".bin"
    filename = f"slide-image-{counter:03d}{suffix}"
    return CanonicalAsset(filename=filename, data=data, source_part=part, media_type=MIME_BY_SUFFIX.get(suffix, ""))


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #


def _parse_pdf(
    source: Path,
    raw: bytes,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    warnings: list[str] = []
    pages: list[str] = []
    ocr_used = False
    try:
        import pymupdf  # type: ignore[import-not-found]

        with pymupdf.open(source) as document:
            for page_index in range(document.page_count):
                pages.append(str(document.load_page(page_index).get_text("text")))
            if not any(page.strip() for page in pages):
                # Scanned PDF: render a bounded number of pages and OCR them.
                ocr_pages: list[str] = []
                ocr_limit = min(document.page_count, 20)
                for page_index in range(ocr_limit):
                    page = document.load_page(page_index)
                    pixmap = page.get_pixmap(dpi=200)
                    result = ocr_image_bytes(pixmap.tobytes("png"))
                    warnings.extend(result.warnings)
                    ocr_pages.append(result.text)
                    if result.text.strip():
                        ocr_used = True
                if ocr_used:
                    pages = ocr_pages
                    if document.page_count > ocr_limit:
                        warnings.append(
                            f"OCR covered the first {ocr_limit} pages of {document.page_count}; "
                            "later pages remain untranscribed."
                        )
    except Exception:
        pages = []
    if not pages:
        pages = _pdf_text_from_bytes(raw)
        if pages:
            warnings.append("PDF text was recovered with the byte-scan fallback; layout may be approximate.")
    if not pages:
        raise CanonicalParseError(
            "Could not read a text layer from this PDF, and OCR did not produce text; "
            "the document may be a scan or Tesseract may be unavailable."
        )
    if not ocr_used and not any(page.strip() for page in pages):
        raise CanonicalParseError(
            "This PDF has no text layer (it looks like a scan), and OCR did not produce text."
        )

    blocks: list[str] = []
    for page_number, page_text in enumerate(pages, start=1):
        blocks.append(f"<!-- page: {page_number} -->")
        stripped = page_text.strip()
        if not stripped:
            warnings.append(
                f"Page {page_number}: no text layer or OCR text was found."
            )
            blocks.append("")
            continue
        blocks.append(_normalize_pdf_text(stripped))
        blocks.append("")
    if ocr_used:
        warnings.insert(0, "Scanned PDF text was transcribed with Tesseract OCR; verify against the page image.")
    return _join_blocks(blocks), _dedupe(warnings), [], len(pages), None


def _pdf_text_from_bytes(raw: bytes) -> list[str]:
    try:
        from .preview import _extract_pdf_stream_texts  # type: ignore[attr-defined]
    except Exception:
        return []
    try:
        texts = _extract_pdf_stream_texts(raw)
    except Exception:
        return []
    return [text for text in texts if text.strip()]


def _normalize_pdf_text(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if blank:
                continue
            blank = True
            collapsed.append("")
            continue
        blank = False
        collapsed.append(line)
    return "\n".join(collapsed).strip()


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #


def html_to_markdown(raw: str, source_url: str = "") -> tuple[str, list[str]]:
    """Convert an HTML page to block-structured Markdown.

    trafilatura gives the best content selection, but it sometimes joins
    adjacent blocks without any separator ("MITLast updated: ..."), so a
    Markdown result without block structure falls back to the built-in
    block-aware extractor. Both paths drop scripts, styles and chrome.
    """

    cleaned = _strip_html_noise(raw)
    warnings: list[str] = []
    markdown = ""
    try:
        import trafilatura  # type: ignore[import-not-found]

        extracted = trafilatura.extract(
            cleaned,
            url=source_url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_formatting=True,
        )
        if isinstance(extracted, str):
            markdown = extracted.strip()
    except Exception:
        markdown = ""
    if markdown and "\n" not in markdown and len(markdown) > 120:
        # One long line means blocks were concatenated; the built-in extractor
        # preserves paragraph/heading boundaries, which citations rely on.
        markdown = ""
    if not markdown:
        converter = _HTMLExtractor()
        try:
            converter.feed(cleaned)
            converter.close()
        except Exception:
            pass
        markdown = converter.markdown().strip()
        if markdown:
            warnings.append(
                "HTML was converted with the built-in extractor; scripts and navigation were dropped."
            )
    return markdown, warnings


def _parse_html(
    raw: bytes,
    source_url: str,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    decoded = raw.decode("utf-8", errors="replace")
    markdown, warnings = html_to_markdown(decoded, source_url)
    if not markdown:
        raise CanonicalParseError("No readable body text was found in the HTML source.")
    title = _first_markdown_heading(markdown)
    if not title:
        markdown = f"# {_html_title(decoded) or 'Web page'}\n\n{markdown}"
    return markdown, warnings, [], None, None


_HTML_NOISE_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg", "template")


def _strip_html_noise(raw: str) -> str:
    cleaned = raw
    for tag in _HTML_NOISE_TAGS:
        cleaned = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}\s*>",
            " ",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(rf"<{tag}\b[^>]*/?>", " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _html_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html_module.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


class _HTMLExtractor(HTMLParser):
    """Minimal readable-text extractor used when trafilatura is unavailable."""

    BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "blockquote",
        "pre",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "form", "iframe", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._lines: list[str] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading: int = 0
        self._in_pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {f"h{level}" for level in range(1, 7)}:
            self._flush()
            self._heading = int(tag[1])
        elif tag == "pre":
            self._in_pre += 1
            self._flush()
        elif tag in self.BLOCK_TAGS:
            self._flush()
        elif tag in {"br", "hr"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in {f"h{level}" for level in range(1, 7)}:
            self._flush()
            self._heading = 0
        elif tag == "pre":
            self._flush()
            self._in_pre = max(0, self._in_pre - 1)
        elif tag in self.BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_pre:
            self._buffer.append(data)
        else:
            self._buffer.append(re.sub(r"\s+", " ", data))

    def _flush(self) -> None:
        text = "".join(self._buffer).strip()
        self._buffer = []
        if not text:
            return
        if self._heading:
            self._lines.append(f"{'#' * self._heading} {text}")
        elif self._in_pre:
            self._lines.append("```\n" + text + "\n```")
        else:
            self._lines.append(text)

    def markdown(self) -> str:
        return "\n\n".join(self._lines)


# --------------------------------------------------------------------------- #
# Plain text, Markdown, code, images
# --------------------------------------------------------------------------- #


def _parse_text_like(
    raw: bytes,
    filename: str,
    *,
    markdown: bool,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    text = _decode_text(raw)
    warnings: list[str] = []
    if markdown:
        text = strip_front_matter(text)
    return text.strip(), warnings, [], None, None


def _parse_image(
    raw: bytes,
    filename: str,
) -> tuple[str, list[str], list[CanonicalAsset], int | None, int | None]:
    asset = CanonicalAsset(
        filename=f"original-{_safe_original_name(filename)}",
        data=raw,
        source_part="source",
        media_type=MIME_BY_SUFFIX.get(Path(filename).suffix.lower(), ""),
    )
    ocr = ocr_image_bytes(raw)
    title = Path(filename).stem
    body = f"# {title}\n\n![{title}](assets/{asset.filename})"
    warnings = list(ocr.warnings)
    if ocr.text.strip():
        body += f"\n\n## OCR text\n\n{ocr.text.strip()}"
        warnings.insert(0, "Image text was transcribed with Tesseract OCR; verify against the image.")
    else:
        body += (
            "\n\n> This image was stored as a resource. No OCR text was extracted, "
            "so it has no transcribed text."
        )
        if ocr.available:
            warnings.append("Image resources have no OCR text; only the image itself is available.")
    return body, _dedupe(warnings), [asset], None, None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    separator = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _join_blocks(blocks: Iterable[str]) -> str:
    text = "\n\n".join(block for block in blocks if block is not None)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n" if text.strip() else ""


def _count_lines(blocks: Iterable[str]) -> int:
    text = "\n\n".join(block for block in blocks if block is not None)
    return text.count("\n") + 1 if text else 0


def plain_text_preview(markdown: str, max_chars: int = 200) -> str:
    """A readable one-paragraph preview of a Markdown body.

    Resource summaries are rendered as prose in the library; raw Markdown
    control characters and anchor comments would look like source code there.
    """

    text = strip_front_matter(markdown)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}[>*-]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`+", "", text)
    text = re.sub(r"\*\*|__", "", text)
    # Footnote definitions would otherwise leave a bare ":" in the preview.
    text = re.sub(r"^\s*\[\^[^\]]+\]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    # Markdown table separators and pipes are syntax, not prose.
    text = re.sub(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*$", "", text, flags=re.MULTILINE)
    text = text.replace("|", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def anchors_for_body(body: str, source_type: str) -> list[DocumentAnchor]:
    """Derive citable anchors from the assembled Markdown body.

    PDF bodies carry ``<!-- page: N -->`` markers, PPTX bodies carry
    ``## Slide N — title`` headings, and every other source type is anchored
    by its Markdown headings.  Anchors are computed from the final text so the
    recorded line numbers always match what a reader sees.
    """

    anchors: list[DocumentAnchor] = []
    if source_type == "pdf":
        for line_number, line in enumerate(body.splitlines(), start=1):
            match = re.match(r"^<!--\s*page:\s*(\d+)\s*-->$", line.strip())
            if match:
                anchors.append(
                    DocumentAnchor(
                        kind="page",
                        index=int(match.group(1)),
                        label=f"page {match.group(1)}",
                        line=line_number,
                    )
                )
        return anchors
    if source_type == "pptx":
        for line_number, line in enumerate(body.splitlines(), start=1):
            match = re.match(r"^##\s+Slide\s+(\d+)\s*(?:—\s*(.*?))?\s*$", line.strip())
            if match:
                label = (match.group(2) or "").strip()
                anchors.append(
                    DocumentAnchor(
                        kind="slide",
                        index=int(match.group(1)),
                        label=label,
                        line=line_number,
                    )
                )
        return anchors
    return _heading_anchors(body)


def _heading_anchors(markdown: str) -> list[DocumentAnchor]:
    anchors: list[DocumentAnchor] = []
    in_fence = False
    for number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", stripped)
        if match:
            anchors.append(
                DocumentAnchor(
                    kind="heading",
                    index=len(anchors) + 1,
                    label=match.group(2).strip(),
                    line=number,
                )
            )
    return anchors


def _first_markdown_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#{1,6}\s+(.*\S)\s*$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _looks_like_markdown_heading(text: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+", text.lstrip()))


def _read_zip_part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return archive.read(name)
    except KeyError:
        return None
    except (OSError, zipfile.BadZipFile):
        return None


def _read_relationships(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    raw = _read_zip_part(archive, part)
    if raw is None:
        return {}
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    relationships: dict[str, str] = {}
    for node in root.findall(f"{_PKG_REL}Relationship"):
        rel_id = str(node.get("Id") or "").strip()
        target = str(node.get("Target") or "").strip()
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _safe_original_name(name: str) -> str:
    cleaned = Path(str(name or "")).name.strip()
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    cleaned = re.sub(r'[<>:"|?*]', "-", cleaned)
    cleaned = cleaned.replace("/", "-").replace("\\", "-")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "source"
    if len(cleaned) > 120:
        suffix = Path(cleaned).suffix
        stem = Path(cleaned).stem[: 120 - len(suffix)]
        cleaned = f"{stem}{suffix}"
    return cleaned


def _sha256_hex(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
