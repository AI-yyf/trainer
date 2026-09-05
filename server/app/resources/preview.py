"""Three-tier preview pipeline for resources.

Tier RICH (Rich Preview): CodeMirror 6 / Shiki for syntax-highlighted code/text,
plus native rendering for images, audio and video.
Tier CONVERTED (Converted): Text extraction for document formats (PDF, DOCX, etc.).
Tier METADATA (Metadata): File info only, with native-open fallback.
"""

from __future__ import annotations

import csv
import html as html_escape
import io
import json
import posixpath
import re
import stat
import sys
import tarfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class PreviewTier(StrEnum):
    """Preview tier ordered by richness."""

    RICH = "rich"  # Syntax-highlighted or native-rendered preview
    CONVERTED = "converted"  # Converted to Markdown / plain text
    METADATA = "metadata"  # File metadata + native open fallback


TIER_RICH = PreviewTier.RICH
TIER_CONVERTED = PreviewTier.CONVERTED
TIER_METADATA = PreviewTier.METADATA

ARCHIVE_CONVERTED_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tbz2",
    ".txz",
)
ARCHIVE_METADATA_SUFFIXES = (".7z", ".rar", ".gz", ".bz2")
LEGACY_OFFICE_METADATA_SUFFIXES = {".doc", ".xls", ".ppt"}


@dataclass(slots=True)
class PreviewResult:
    """Result from a preview operation."""

    tier: PreviewTier
    file_path: str
    content: str | None = None
    html: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    language: str | None = None
    can_native_open: bool = False


# Mapping of file extension -> (best_tier, language_id, is_native_media)
# best_tier is the richest tier natively supported for this type.
_EXTENSION_MAP: dict[str, tuple[PreviewTier, str | None, bool]] = {
    # Code
    ".py": (TIER_RICH, "python", False),
    ".ts": (TIER_RICH, "typescript", False),
    ".tsx": (TIER_RICH, "tsx", False),
    ".js": (TIER_RICH, "javascript", False),
    ".jsx": (TIER_RICH, "jsx", False),
    ".go": (TIER_RICH, "go", False),
    ".rs": (TIER_RICH, "rust", False),
    ".java": (TIER_RICH, "java", False),
    ".c": (TIER_RICH, "c", False),
    ".cpp": (TIER_RICH, "cpp", False),
    ".h": (TIER_RICH, "c", False),
    ".hpp": (TIER_RICH, "cpp", False),
    ".cs": (TIER_RICH, "csharp", False),
    ".rb": (TIER_RICH, "ruby", False),
    ".php": (TIER_RICH, "php", False),
    ".swift": (TIER_RICH, "swift", False),
    ".kt": (TIER_RICH, "kotlin", False),
    ".scala": (TIER_RICH, "scala", False),
    ".sql": (TIER_RICH, "sql", False),
    ".sh": (TIER_RICH, "bash", False),
    ".bash": (TIER_RICH, "bash", False),
    ".zsh": (TIER_RICH, "bash", False),
    ".ps1": (TIER_RICH, "powershell", False),
    ".psm1": (TIER_RICH, "powershell", False),
    ".psd1": (TIER_RICH, "powershell", False),
    ".r": (TIER_RICH, "r", False),
    ".lua": (TIER_RICH, "lua", False),
    ".pl": (TIER_RICH, "perl", False),
    ".pm": (TIER_RICH, "perl", False),
    # Text
    ".txt": (TIER_RICH, "text", False),
    ".log": (TIER_RICH, "text", False),
    ".ini": (TIER_RICH, "ini", False),
    ".cfg": (TIER_RICH, "text", False),
    ".conf": (TIER_RICH, "text", False),
    ".properties": (TIER_RICH, "text", False),
    ".env": (TIER_RICH, "text", False),
    # Markdown
    ".md": (TIER_RICH, "markdown", False),
    ".markdown": (TIER_RICH, "markdown", False),
    ".mdown": (TIER_RICH, "markdown", False),
    ".mkd": (TIER_RICH, "markdown", False),
    ".mkdn": (TIER_RICH, "markdown", False),
    # JSON
    ".json": (TIER_RICH, "json", False),
    ".jsonc": (TIER_RICH, "json", False),
    ".geojson": (TIER_RICH, "json", False),
    ".ipynb": (TIER_RICH, "json", False),
    # YAML
    ".yaml": (TIER_RICH, "yaml", False),
    ".yml": (TIER_RICH, "yaml", False),
    # HTML / XML
    ".html": (TIER_RICH, "html", False),
    ".htm": (TIER_RICH, "html", False),
    ".xhtml": (TIER_RICH, "html", False),
    ".xml": (TIER_RICH, "xml", False),
    ".xsd": (TIER_RICH, "xml", False),
    ".xsl": (TIER_RICH, "xml", False),
    ".xslt": (TIER_RICH, "xml", False),
    # Diff
    ".diff": (TIER_RICH, "diff", False),
    ".patch": (TIER_RICH, "diff", False),
    # CSV / TSV
    ".csv": (TIER_RICH, "csv", False),
    ".tsv": (TIER_RICH, "tsv", False),
    # Documents -> converted
    ".pdf": (TIER_CONVERTED, None, False),
    ".docx": (TIER_CONVERTED, None, False),
    ".docm": (TIER_CONVERTED, None, False),
    ".doc": (TIER_CONVERTED, None, False),
    ".xlsx": (TIER_CONVERTED, None, False),
    ".xlsm": (TIER_CONVERTED, None, False),
    ".xls": (TIER_CONVERTED, None, False),
    ".pptx": (TIER_CONVERTED, None, False),
    ".pptm": (TIER_CONVERTED, None, False),
    ".ppt": (TIER_CONVERTED, None, False),
    ".odt": (TIER_CONVERTED, None, False),
    ".ods": (TIER_CONVERTED, None, False),
    ".odp": (TIER_CONVERTED, None, False),
    ".rtf": (TIER_CONVERTED, None, False),
    ".epub": (TIER_CONVERTED, None, False),
    ".eml": (TIER_CONVERTED, None, False),
    # Images -> rich (native)
    ".png": (TIER_RICH, None, True),
    ".jpg": (TIER_RICH, None, True),
    ".jpeg": (TIER_RICH, None, True),
    ".webp": (TIER_RICH, None, True),
    ".gif": (TIER_RICH, None, True),
    ".bmp": (TIER_RICH, None, True),
    ".svg": (TIER_RICH, "svg", True),
    ".ico": (TIER_RICH, None, True),
    # Audio -> rich (native)
    ".mp3": (TIER_RICH, None, True),
    ".wav": (TIER_RICH, None, True),
    ".ogg": (TIER_RICH, None, True),
    ".flac": (TIER_RICH, None, True),
    ".m4a": (TIER_RICH, None, True),
    ".aac": (TIER_RICH, None, True),
    # Video -> rich (native)
    ".mp4": (TIER_RICH, None, True),
    ".webm": (TIER_RICH, None, True),
    ".avi": (TIER_RICH, None, True),
    ".mov": (TIER_RICH, None, True),
    ".mkv": (TIER_RICH, None, True),
    ".flv": (TIER_RICH, None, True),
    # Archives / binary -> metadata unless promoted by archive-specific priority above.
    ".zip": (TIER_METADATA, None, False),
    ".tar": (TIER_METADATA, None, False),
    ".gz": (TIER_METADATA, None, False),
    ".7z": (TIER_METADATA, None, False),
    ".rar": (TIER_METADATA, None, False),
    ".tgz": (TIER_METADATA, None, False),
    ".bz2": (TIER_METADATA, None, False),
}


def _get_file_info(file_path: str) -> tuple[PreviewTier, str | None, bool]:
    """Return (best_tier, language_id, is_native_media) for a given path."""
    lowered_name = Path(file_path).name.lower()
    if any(lowered_name.endswith(suffix) for suffix in ARCHIVE_CONVERTED_SUFFIXES):
        return TIER_CONVERTED, None, False
    if any(lowered_name.endswith(suffix) for suffix in ARCHIVE_METADATA_SUFFIXES):
        return TIER_METADATA, None, False
    suffix = Path(file_path).suffix.lower()
    return _EXTENSION_MAP.get(suffix, (TIER_RICH, None, False))


class PreviewService:
    """Service that provides three-tier previews for local files."""

    def select_tier(self, file_path: str) -> PreviewTier:
        """Select the best preview tier for *file_path*."""
        best_tier, _, _ = _get_file_info(file_path)
        return best_tier

    def get_preview(self, file_path: str, tier: PreviewTier | None = None) -> PreviewResult:
        """Return a ``PreviewResult`` for *file_path* at the requested *tier*.

        When *tier* is ``None`` the tier is auto-selected via :meth:`select_tier`.
        """
        if tier is None:
            tier = self.select_tier(file_path)

        best_tier, lang_id, is_native = _get_file_info(file_path)

        # Tier fallback: if the requested tier is richer than the best tier,
        # fall back to the best tier.
        tier_order = {TIER_RICH: 3, TIER_CONVERTED: 2, TIER_METADATA: 1}
        if tier_order[tier] > tier_order[best_tier]:
            tier = best_tier

        if tier == TIER_RICH:
            if is_native:
                return self._render_native_media(file_path, best_tier, lang_id)
            return self._render_rich_text(file_path, best_tier, lang_id)
        if tier == TIER_CONVERTED:
            return self._render_converted(file_path, best_tier, lang_id)
        return self._render_metadata(file_path, best_tier, lang_id)

    # ------------------------------------------------------------------ #
    # Tier RICH – text / code
    # ------------------------------------------------------------------ #

    def _render_rich_text(
        self,
        file_path: str,
        best_tier: PreviewTier,
        lang_id: str | None,
    ) -> PreviewResult:
        content = _read_file_content(file_path)
        if content is None:
            return PreviewResult(
                tier=TIER_RICH,
                file_path=file_path,
                error="Could not read file content",
                can_native_open=True,
            )

        html = _render_with_shiki(content, lang_id)
        if html is None:
            html = _render_fallback(content)

        return PreviewResult(
            tier=TIER_RICH,
            file_path=file_path,
            content=content,
            html=html,
            language=lang_id,
            can_native_open=True,
            metadata=_structured_preview_metadata(file_path, content, lang_id),
        )

    # ------------------------------------------------------------------ #
    # Tier RICH – native media (images / audio / video)
    # ------------------------------------------------------------------ #

    def _render_native_media(
        self,
        file_path: str,
        best_tier: PreviewTier,
        lang_id: str | None,
    ) -> PreviewResult:
        path = Path(file_path)
        suffix = path.suffix.lower()
        safe_path = html_escape.escape(str(path.resolve()))

        # Determine HTML tag based on media type
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico"}
        audio_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
        video_exts = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv"}

        if suffix in image_exts:
            html = f'<img src="{safe_path}" alt="{html_escape.escape(path.name)}" style="max-width:100%;" />'
        elif suffix in audio_exts:
            html = f'<audio controls src="{safe_path}" style="width:100%;"></audio>'
        elif suffix in video_exts:
            html = f'<video controls src="{safe_path}" style="max-width:100%;"></video>'
        else:
            html = f'<p>Media: {html_escape.escape(path.name)}</p>'

        return PreviewResult(
            tier=TIER_RICH,
            file_path=file_path,
            content=None,
            html=html,
            language=lang_id,
            can_native_open=True,
            metadata=_get_file_metadata(file_path),
        )

    # ------------------------------------------------------------------ #
    # Tier CONVERTED
    # ------------------------------------------------------------------ #

    def _render_converted(
        self,
        file_path: str,
        best_tier: PreviewTier,
        lang_id: str | None,
    ) -> PreviewResult:
        suffix = Path(file_path).suffix.lower()
        is_archive = _is_archive_preview_candidate(file_path)
        content = _convert_with_markitdown(file_path)
        if content is None:
            content = get_structured_preview_markdown(file_path)
        if content is None and suffix == ".pdf":
            content = _convert_pdf_to_markdown(file_path)
        if content is None and suffix in {".docx", ".pptx"}:
            content = _convert_openxml_to_markdown(file_path)
        if content is None and suffix in {".odt", ".ods", ".odp"}:
            content = _convert_odf_to_markdown(file_path)
        if content is None and suffix == ".rtf":
            content = _convert_rtf_to_markdown(file_path)
        if content is None and is_archive:
            content = _convert_archive_to_markdown(file_path)
        if content is None and suffix in LEGACY_OFFICE_METADATA_SUFFIXES:
            return self._render_metadata(file_path, best_tier, lang_id)
        if content is None and not is_archive:
            content = _read_file_content(file_path)

        if content is None:
            if is_archive:
                return self._render_metadata(file_path, best_tier, lang_id)
            return PreviewResult(
                tier=TIER_CONVERTED,
                file_path=file_path,
                error="Could not extract text from file",
                can_native_open=True,
            )

        return PreviewResult(
            tier=TIER_CONVERTED,
            file_path=file_path,
            content=content,
            html=_markdown_to_html(content),
            language="markdown" if _looks_like_markdown(content) else "text",
            can_native_open=True,
            metadata=_structured_preview_metadata(file_path, content, lang_id) or get_structured_preview_data(file_path),
        )

    # ------------------------------------------------------------------ #
    # Tier METADATA
    # ------------------------------------------------------------------ #

    def _render_metadata(
        self,
        file_path: str,
        best_tier: PreviewTier,
        lang_id: str | None,
    ) -> PreviewResult:
        metadata = _get_file_metadata(file_path)
        can_open = _can_native_open(file_path)
        html = _build_metadata_html(metadata, file_path, can_open)

        return PreviewResult(
            tier=TIER_METADATA,
            file_path=file_path,
            content=_format_metadata_text(metadata),
            html=html,
            metadata=metadata,
            can_native_open=can_open,
        )


# ======================================================================
# Helpers
# ====================================================================== #

def _read_file_content(file_path: str, max_bytes: int = 1024 * 1024) -> str | None:
    """Read file content with a size limit."""
    try:
        path = Path(file_path)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(max_bytes)
    except Exception:
        return None


def _get_file_metadata(file_path: str) -> dict[str, Any]:
    """Extract file metadata for Tier METADATA."""
    try:
        path = Path(file_path)
        if not path.exists():
            return {"error": "File does not exist"}
        stat = path.stat()
        return {
            "name": path.name,
            "size": stat.st_size,
            "size_human": _format_size(stat.st_size),
            "modified": stat.st_mtime,
            "modified_iso": _format_timestamp(stat.st_mtime),
            "extension": path.suffix.lower(),
            "is_binary": _is_binary_file(path),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _format_size(size: int | float) -> str:
    """Format file size in human-readable format."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size = size / 1024
    return f"{size:.1f} PB"


def _format_timestamp(timestamp: float) -> str:
    """Format timestamp as an ISO string."""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _is_binary_file(path: Path) -> bool:
    """Check whether *path* points to a binary file."""
    binary_extensions = {
        ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".zip", ".tar", ".gz", ".7z", ".rar",
        ".epub",
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico",
        ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac",
        ".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv",
    }
    if path.suffix.lower() in binary_extensions:
        return True
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
            return b"\x00" in chunk
    except Exception:
        return True


def _can_native_open(file_path: str) -> bool:
    """Check whether the file can be opened with the system default application."""
    path = Path(file_path)
    if sys.platform == "win32":
        return path.exists() and path.suffix != ""
    return path.exists()


def _build_metadata_html(metadata: dict[str, Any], file_path: str, can_open: bool) -> str:
    """Build HTML for metadata display."""
    safe_path = html_escape.escape(file_path)
    rows: list[str] = []
    for key, value in metadata.items():
        if key == "error":
            rows.append(
                f'<div class="metadata-error">{html_escape.escape(str(value))}</div>'
            )
            continue
        display_key = key.replace("_", " ").title()
        display_value = html_escape.escape(str(value))
        rows.append(
            f'<div class="metadata-row">'
            f'<span class="metadata-key">{display_key}:</span> '
            f'<span class="metadata-value">{display_value}</span>'
            f"</div>"
        )

    open_button = ""
    if can_open:
        open_button = (
            f'<button class="native-open-btn" data-path="{safe_path}" '
            f'onclick="window.previewNativeOpen(\'{safe_path}\')">'
            f"Open in Default App</button>"
        )

    return (
        f'<div class="preview-tier-metadata">'
        f'<div class="file-metadata">{ "".join(rows) }</div>'
        f"{open_button}"
        f"</div>"
    )


def _format_metadata_text(metadata: dict[str, Any]) -> str:
    """Format metadata as plain text."""
    if "error" in metadata:
        return f"Error: {metadata['error']}"
    lines: list[str] = []
    for key, value in metadata.items():
        if key == "is_binary":
            value = "Yes" if value else "No"
        display_key = key.replace("_", " ").title()
        lines.append(f"{display_key}: {value}")
    return "\n".join(lines)


# ======================================================================
# Rendering helpers
# ====================================================================== #

def _render_with_shiki(code: str, language: str | None) -> str | None:
    """Render code with Shiki syntax highlighting if available."""
    try:
        from shiki import highlighter as shiki_highlighter  # type: ignore[import-not-found]

        if language is None:
            return None

        lang_map = {
            "python": "python",
            "typescript": "typescript",
            "tsx": "tsx",
            "javascript": "javascript",
            "jsx": "jsx",
            "go": "go",
            "rust": "rust",
            "java": "java",
            "c": "c",
            "cpp": "cpp",
            "csharp": "csharp",
            "ruby": "ruby",
            "php": "php",
            "swift": "swift",
            "kotlin": "kotlin",
            "scala": "scala",
            "sql": "sql",
            "bash": "bash",
            "powershell": "powershell",
            "json": "json",
            "yaml": "yaml",
            "html": "html",
            "xml": "xml",
            "markdown": "markdown",
            "diff": "diff",
            "csv": "csv",
            "tsv": "tsv",
            "ini": "ini",
            "svg": "svg",
        }
        shiki_lang = lang_map.get(language, language)
        highlighter = shiki_highlighter(theme="github-dark", langs=[shiki_lang])
        return highlighter.code_to_html(code, lang=shiki_lang)
    except Exception:
        return None


def _render_fallback(code: str) -> str:
    """Fallback HTML rendering without Shiki."""
    escaped = html_escape.escape(code)
    lines = escaped.split("\n")
    numbered = "\n".join(
        f'<span class="line-number">{i + 1}</span>'
        f'<span class="line-content">{line}</span>'
        for i, line in enumerate(lines)
    )
    return f"<pre><code>{numbered}</code></pre>"


def _convert_with_markitdown(file_path: str) -> str | None:
    """Convert file using MarkItDown library if available."""
    try:
        from markitdown import MarkItDown  # type: ignore[import-not-found]

        converter = MarkItDown()
        result = converter.convert(file_path)
        return result.text_content
    except Exception:
        return None


def _convert_pdf_to_markdown(file_path: str) -> str | None:
    """Extract plain text from PDF pages using PyMuPDF as a local fallback."""
    if Path(file_path).suffix.lower() != ".pdf":
        return None
    try:
        import fitz  # type: ignore[import-not-found]

        document = fitz.open(file_path)
        page_texts: list[str] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            raw_text = page.get_text("text")
            if not isinstance(raw_text, str):
                continue
            text = raw_text.strip()
            if not text:
                continue
            page_texts.append(f"# Page {page_index + 1}\n\n{text}")
        document.close()
        if not page_texts:
            return None
        return "\n\n".join(page_texts)
    except Exception:
        return _convert_pdf_bytes_to_markdown(file_path)


def _convert_pdf_bytes_to_markdown(file_path: str) -> str | None:
    """Extract plain text from a lightweight PDF byte scan fallback."""
    path = Path(file_path)
    try:
        data = path.read_bytes()
    except Exception:
        return None

    page_texts: list[str] = []
    for page_index, stream_text in enumerate(_extract_pdf_stream_texts(data), start=1):
        text = stream_text.strip()
        if not text:
            continue
        page_texts.append(f"# Page {page_index}\n\n{text}")

    if page_texts:
        return "\n\n".join(page_texts)

    fallback_text = _extract_pdf_literal_text(data).strip()
    if fallback_text:
        return f"# Page 1\n\n{fallback_text}"
    return None


def _extract_pdf_stream_texts(data: bytes) -> list[str]:
    stream_pattern = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
    texts: list[str] = []
    for match in stream_pattern.finditer(data):
        stream = match.group(1)
        candidates = [stream]
        try:
            candidates.append(zlib.decompress(stream))
        except Exception:
            pass
        for candidate in candidates:
            text = _extract_pdf_literal_text(candidate)
            if text.strip():
                texts.append(text)
                break
    return texts


def _extract_pdf_literal_text(data: bytes) -> str:
    if not data:
        return ""
    fragments: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\()])*\)", data):
        decoded = _decode_pdf_literal_string(match.group(0)[1:-1])
        if decoded.strip():
            fragments.append(decoded)
    return " ".join(fragments)


def _decode_pdf_literal_string(raw: bytes) -> str:
    text: list[str] = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char != 0x5C:  # backslash
            text.append(chr(char))
            index += 1
            continue
        index += 1
        if index >= length:
            break
        escaped = raw[index]
        index += 1
        if escaped == ord("n"):
            text.append("\n")
        elif escaped == ord("r"):
            text.append("\r")
        elif escaped == ord("t"):
            text.append("\t")
        elif escaped == ord("b"):
            text.append("\b")
        elif escaped == ord("f"):
            text.append("\f")
        elif escaped in {ord("("), ord(")"), ord("\\"), ord("/")}:
            text.append(chr(escaped))
        elif 0x30 <= escaped <= 0x37:
            octal_digits = [chr(escaped)]
            while index < length and len(octal_digits) < 3 and 0x30 <= raw[index] <= 0x37:
                octal_digits.append(chr(raw[index]))
                index += 1
            try:
                text.append(chr(int("".join(octal_digits), 8)))
            except Exception:
                continue
        elif escaped in {ord("\n"), ord("\r")}:
            if escaped == ord("\r") and index < length and raw[index] == ord("\n"):
                index += 1
        else:
            text.append(chr(escaped))
    return "".join(text)


def _convert_openxml_to_markdown(file_path: str) -> str | None:
    """Extract markdown text from DOCX / PPTX OpenXML packages.

    Attempts MarkItDown first (provides richer output), falls back to
    custom XML parsing for PPTX/XLSX, then native zip parsing for DOCX.
    """
    suffix = Path(file_path).suffix.lower()
    if suffix not in {".docx", ".docm", ".pptx", ".pptm"}:
        return None

    # Try MarkItDown first - provides richer output for PPTX/XLSX
    markitdown_result = _convert_with_markitdown(file_path)
    # Guard against MarkItDown returning zip-file listings (indicates extraction failure)
    if markitdown_result and not markitdown_result.startswith("Content from the zip file"):
        return markitdown_result

    # Fall back to custom PPTX XML parsing
    if suffix in {".pptx", ".pptm"}:
        markdown, _structured = _openxml_presentation_preview(file_path)
        return markdown

    # Fall back to DOCX XML parsing
    try:
        with zipfile.ZipFile(file_path) as archive:
            if suffix == ".docx":
                candidate_paths = ["word/document.xml"]
            else:
                candidate_paths = sorted(
                    name
                    for name in archive.namelist()
                    if name.startswith("ppt/slides/") and name.endswith(".xml")
                )
            paragraphs: list[str] = []
            for candidate_path in candidate_paths:
                try:
                    xml_data = archive.read(candidate_path)
                except KeyError:
                    continue
                try:
                    root = ET.fromstring(xml_data)
                except Exception:
                    continue
                for element in root.iter():
                    if _xml_local_name(element.tag) != "p":
                        continue
                    text_parts = [
                        str(child.text or "")
                        for child in element.iter()
                        if _xml_local_name(child.tag) == "t" and str(child.text or "").strip()
                    ]
                    paragraph = "".join(text_parts).strip()
                    if paragraph:
                        paragraphs.append(paragraph)
            if not paragraphs:
                return None
            return "\n\n".join(paragraphs)
    except Exception:
        return None
    return None


def _convert_odf_to_markdown(file_path: str) -> str | None:
    """Extract simple markdown text from ODT / ODS / ODP ODF packages."""
    suffix = Path(file_path).suffix.lower()
    if suffix not in {".odt", ".ods", ".odp"}:
        return None
    root = _odf_content_root(file_path)
    if root is None:
        return None
    if suffix == ".ods":
        markdown, _structured = _odf_spreadsheet_preview(root, Path(file_path).name)
        return markdown
    if suffix == ".odp":
        return _odf_presentation_preview(root, Path(file_path).name)
    return _odf_text_preview(root, Path(file_path).name)


def _convert_rtf_to_markdown(file_path: str) -> str | None:
    """Extract plain text from RTF documents with a lightweight local parser."""
    if Path(file_path).suffix.lower() != ".rtf":
        return None
    try:
        raw = Path(file_path).read_text(encoding="latin-1", errors="ignore")
    except Exception:
        return None
    start = raw.lower().find("\\pard")
    if start != -1:
        raw = raw[start:]
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(
        r"\\'[0-9a-fA-F]{2}",
        lambda match: bytes.fromhex(match.group(0)[2:]).decode("latin-1", errors="ignore"),
        raw,
    )
    raw = raw.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    raw = re.sub(r"\\[a-zA-Z]+\d* ?", "", raw)
    raw = raw.replace("{", "").replace("}", "").replace("\\", "")
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line and line.lower() not in {"rtf", "ansi"}]
    if not lines:
        return None
    return "\n".join(lines)


def _convert_eml_to_markdown(file_path: str) -> str | None:
    """Extract a readable markdown summary from an RFC 822 email message."""
    path = Path(file_path)
    if path.suffix.lower() != ".eml" or not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            message = BytesParser(policy=policy.default).parse(handle)
    except Exception:
        return None

    subject = _normalize_preview_text(str(message.get("subject", "") or ""))
    sender = _normalize_preview_text(str(message.get("from", "") or ""))
    to = _normalize_preview_text(str(message.get("to", "") or ""))
    cc = _normalize_preview_text(str(message.get("cc", "") or ""))
    date = _normalize_preview_text(str(message.get("date", "") or ""))
    attachments = list(message.iter_attachments()) if hasattr(message, "iter_attachments") else []

    body_text = _extract_email_body_text(message)
    if body_text is None:
        return None

    title = subject or path.name
    lines = [f"# {title}"]
    if sender:
        lines.append(f"- From: {sender}")
    if to:
        lines.append(f"- To: {to}")
    if cc:
        lines.append(f"- Cc: {cc}")
    if date:
        lines.append(f"- Date: {date}")
    if attachments:
        lines.append(f"- Attachments: {len(attachments)}")
    lines.append("")
    lines.append("## Body")
    lines.extend(_paragraph_lines(body_text))
    return "\n".join(line for line in lines if line.strip())


def _extract_email_body_text(message: Any) -> str | None:
    plain_body: str | None = None
    html_body: str | None = None

    try:
        body_part = message.get_body(preferencelist=("plain",))
    except Exception:
        body_part = None
    if body_part is not None:
        try:
            plain_body = str(body_part.get_content() or "")
        except Exception:
            plain_body = None

    if not plain_body:
        try:
            html_part = message.get_body(preferencelist=("html",))
        except Exception:
            html_part = None
        if html_part is not None:
            try:
                html_body = str(html_part.get_content() or "")
            except Exception:
                html_body = None

    if plain_body:
        return plain_body
    if html_body:
        outline = _extract_html_outline(html_body)
        if outline:
            return str(outline.get("content") or "").strip() or html_body
        return html_body

    try:
        payload = message.get_content()
    except Exception:
        payload = None
    if isinstance(payload, str) and payload.strip():
        return payload
    return None


def _paragraph_lines(content: str, *, max_paragraphs: int = 8) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n{2,}", str(content or "").replace("\r\n", "\n").replace("\r", "\n")):
        text = _normalize_preview_text(paragraph)
        if text:
            paragraphs.append(text)
        if len(paragraphs) >= max_paragraphs:
            break
    return paragraphs


def _convert_epub_to_markdown(file_path: str) -> str | None:
    """Extract a readable markdown summary from an EPUB package."""
    preview = _epub_preview_data(file_path)
    if not preview:
        return None
    content = str(preview.get("content") or "").strip()
    return content or None


def _epub_preview_data(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if path.suffix.lower() != ".epub" or not path.exists():
        return {}
    try:
        with zipfile.ZipFile(path) as archive:
            opf_path = _epub_opf_path(archive)
            if opf_path is None:
                return {}
            return _epub_preview_data_from_archive(path, archive, opf_path)
    except Exception:
        return {}


def _epub_opf_path(archive: zipfile.ZipFile) -> str | None:
    try:
        container_root = ET.fromstring(archive.read("META-INF/container.xml"))
    except Exception:
        return None
    for element in container_root.iter():
        if _xml_local_name(element.tag) != "rootfile":
            continue
        opf_path = _normalize_preview_text(str(element.attrib.get("full-path") or ""))
        if opf_path:
            return opf_path
    return None


def _epub_preview_data_from_archive(path: Path, archive: zipfile.ZipFile, opf_path: str) -> dict[str, Any]:
    try:
        opf_root = ET.fromstring(archive.read(opf_path))
    except Exception:
        return {}
    manifest: dict[str, tuple[str, str]] = {}
    spine: list[str] = []
    title: str | None = None
    for element in opf_root.iter():
        local_name = _xml_local_name(element.tag)
        if local_name == "title" and title is None:
            text = _normalize_preview_text("".join(element.itertext()))
            if text:
                title = text
        elif local_name == "item":
            item_id = _normalize_preview_text(str(element.attrib.get("id") or ""))
            href = _normalize_preview_text(str(element.attrib.get("href") or ""))
            media_type = _normalize_preview_text(str(element.attrib.get("media-type") or ""))
            if item_id and href:
                manifest[item_id] = (href, media_type)
        elif local_name == "itemref":
            idref = _normalize_preview_text(str(element.attrib.get("idref") or ""))
            if idref:
                spine.append(idref)

    opf_dir = posixpath.dirname(opf_path)
    chapters: list[dict[str, Any]] = []
    for index, idref in enumerate(spine[:8], start=1):
        href_media = manifest.get(idref)
        if href_media is None:
            continue
        href, media_type = href_media
        chapter_path = posixpath.normpath(posixpath.join(opf_dir, href))
        try:
            chapter_content = archive.read(chapter_path).decode("utf-8", errors="ignore")
        except Exception:
            continue
        outline = _extract_html_outline(chapter_content)
        chapter_title = ""
        chapter_preview = chapter_content
        if outline:
            chapter_title = str(outline.get("extra", {}).get("title") or "").strip()
            chapter_preview = str(outline.get("content") or "").strip() or chapter_content
        else:
            chapter_preview = _normalize_preview_text(chapter_content)
        if not chapter_preview:
            continue
        if len(chapter_preview) > 2_000:
            chapter_preview = chapter_preview[:2_000].rstrip()
        chapters.append(
            {
                "path": chapter_path,
                "title": chapter_title or Path(href).stem or f"Section {index}",
                "mediaType": media_type,
                "preview": chapter_preview,
            }
        )

    if not chapters:
        return {
            "kind": "document",
            "format": "epub",
            "fileName": path.name,
            "title": title or path.name,
            "sectionCount": len(spine),
            "manifestCount": len(manifest),
            "truncated": False,
            "content": f"# {title or path.name}\n\nEPUB contains no readable spine sections.",
        }

    lines = [f"# {title or path.name}", "", f"Sections: {len(spine)}", f"Readable sections: {len(chapters)}", ""]
    for chapter in chapters:
        lines.append(f"## {chapter['title']}")
        if chapter.get("mediaType"):
            lines.append(f"- Media type: {chapter['mediaType']}")
        lines.append(str(chapter["preview"]))
        lines.append("")
    content = "\n".join(line for line in lines if line is not None).strip()
    return {
        "kind": "document",
        "format": "epub",
        "fileName": path.name,
        "title": title or path.name,
        "sectionCount": len(spine),
        "manifestCount": len(manifest),
        "chapters": chapters,
        "truncated": len(spine) > len(chapters),
        "content": content,
    }


def _odf_content_root(file_path: str) -> ET.Element | None:
    try:
        with zipfile.ZipFile(file_path) as archive:
            content = archive.read("content.xml")
    except Exception:
        return None
    try:
        return ET.fromstring(content)
    except Exception:
        return None


def _odf_text_preview(root: ET.Element, title: str) -> str | None:
    lines = [f"# {title}"]
    for element in root.iter():
        local_name = _xml_local_name(element.tag)
        if local_name not in {"h", "p"}:
            continue
        text = _odf_normalize_text("".join(element.itertext()))
        if not text:
            continue
        if local_name == "h":
            level = _odf_outline_level(element)
            lines.append(f'{"#" * level} {text}')
        else:
            lines.append(text)
    body = "\n\n".join(line for line in lines if line.strip())
    return body if len(lines) > 1 else None


def _odf_presentation_preview(root: ET.Element, title: str) -> str | None:
    slides: list[str] = [f"# {title}"]
    for index, page in enumerate((element for element in root.iter() if _xml_local_name(element.tag) == "page"), start=1):
        page_name = _odf_attr_value(page, "name") or f"Slide {index}"
        paragraphs: list[str] = []
        for element in page.iter():
            local_name = _xml_local_name(element.tag)
            if local_name not in {"h", "p"}:
                continue
            text = _odf_normalize_text("".join(element.itertext()))
            if text:
                paragraphs.append(text)
        if paragraphs:
            slides.append(f"## {page_name}")
            slides.extend(paragraphs)
    body = "\n\n".join(line for line in slides if line.strip())
    return body if len(slides) > 1 else None


def _odf_spreadsheet_preview(root: ET.Element, title: str) -> tuple[str | None, dict[str, Any]]:
    tables = [element for element in root.iter() if _xml_local_name(element.tag) == "table"]
    for table in tables:
        sheet_name = _odf_attr_value(table, "name") or title
        rows: list[list[str]] = []
        for row in table:
            if _xml_local_name(row.tag) != "table-row":
                continue
            cells: list[str] = []
            for cell in row:
                if _xml_local_name(cell.tag) not in {"table-cell", "covered-table-cell"}:
                    continue
                repeated = _odf_int_attr(cell, "number-columns-repeated")
                cell_text = _odf_normalize_text("".join(cell.itertext()))
                repeat_count = max(1, repeated)
                cells.extend([cell_text] * repeat_count)
            if cells:
                rows.append(cells)
        if len(rows) < 1:
            continue
        headers = rows[0]
        data_rows = rows[1 : 1 + STRUCTURED_XLSX_PREVIEW_ROWS]
        markdown = _rows_to_markdown(sheet_name, headers, data_rows)
        structured = {
            "kind": "table",
            "format": "ods",
            "sheetName": sheet_name,
            "columns": headers,
            "rows": data_rows,
            "headers": headers,
            "rowCount": max(0, len(rows) - 1),
            "columnCount": max(len(headers), max((len(row) for row in rows), default=0)),
            "sampleRows": data_rows,
            "truncated": len(rows) - 1 > len(data_rows),
        }
        return markdown, structured
    return None, {}


def _rows_to_markdown(sheet_name: str, headers: list[str], sample_rows: list[list[str]]) -> str | None:
    width = len(headers)
    if width == 0:
        return None
    normalized_headers = [header if header else f"Column {index + 1}" for index, header in enumerate(headers[:width])]
    lines = [f"### {sheet_name}", ""]
    lines.append("| " + " | ".join(normalized_headers) + " |")
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in sample_rows[:STRUCTURED_XLSX_PREVIEW_ROWS]:
        padded = row[:width] + [""] * max(0, width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
    return "\n".join(lines)


def _odf_normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _odf_attr_value(element: ET.Element, local_name: str) -> str:
    for key, value in element.attrib.items():
        if key.endswith(local_name):
            return str(value or "")
    return ""


def _odf_int_attr(element: ET.Element, local_name: str) -> int:
    value = _odf_attr_value(element, local_name)
    try:
        return int(value)
    except Exception:
        return 0


def _odf_outline_level(element: ET.Element) -> int:
    level = _odf_int_attr(element, "outline-level")
    return max(1, min(level or 1, 6))


def _is_archive_preview_candidate(file_path: str) -> bool:
    lowered_name = Path(file_path).name.lower()
    return any(lowered_name.endswith(suffix) for suffix in ARCHIVE_CONVERTED_SUFFIXES)


def _convert_archive_to_markdown(file_path: str) -> str | None:
    """Render archive contents as markdown when MarkItDown does not produce content."""
    path = Path(file_path)
    lowered_name = path.name.lower()
    if lowered_name.endswith(".zip"):
        return _convert_zip_archive_to_markdown(path)
    if any(lowered_name.endswith(suffix) for suffix in {".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz"}):
        return _convert_tar_archive_to_markdown(path)
    return None


def _convert_zip_archive_to_markdown(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries:
                return f"# {path.name}\n\nArchive is empty."
            lines = [f"# {path.name}", "", f"Archive entries: {len(entries)}", "", "## Contents"]
            for info in entries[:30]:
                if info.is_dir():
                    lines.append(f"- `{info.filename}` (directory)")
                    continue
                lines.append(f"- `{info.filename}` ({info.file_size} bytes)")
                snippet = _zip_text_entry_snippet(archive, info.filename)
                if snippet:
                    lines.append(f"  - Preview: {snippet}")
            if len(entries) > 30:
                lines.append(f"- ... {len(entries) - 30} more entries")
            return "\n".join(lines)
    except Exception:
        return None


def _zip_text_entry_snippet(archive: zipfile.ZipFile, name: str) -> str | None:
    try:
        with archive.open(name) as handle:
            data = handle.read(2048)
    except Exception:
        return None
    text = data.decode("utf-8", errors="ignore").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    snippet = " ".join(lines[:3])
    return snippet[:240]


def _convert_tar_archive_to_markdown(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            if not members:
                return f"# {path.name}\n\nArchive is empty."
            lines = [f"# {path.name}", "", f"Archive entries: {len(members)}", "", "## Contents"]
            for member in members[:30]:
                if member.isdir():
                    lines.append(f"- `{member.name}` (directory)")
                    continue
                kind = "symlink" if member.issym() else "file"
                lines.append(f"- `{member.name}` ({kind}, {member.size} bytes)")
                if member.isfile() and member.size <= 2048:
                    snippet = _tar_text_entry_snippet(archive, member)
                    if snippet:
                        lines.append(f"  - Preview: {snippet}")
            if len(members) > 30:
                lines.append(f"- ... {len(members) - 30} more entries")
            return "\n".join(lines)
    except Exception:
        return None


def _tar_text_entry_snippet(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str | None:
    try:
        extracted = archive.extractfile(member)
        if extracted is None:
            return None
        data = extracted.read(2048)
    except Exception:
        return None
    text = data.decode("utf-8", errors="ignore").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return " ".join(lines[:3])[:240]


def _markdown_to_html(markdown: str) -> str:
    """Simple Markdown-to-HTML converter for converted previews."""
    escaped = html_escape.escape(markdown)
    lines = escaped.split("\n")
    html_lines: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                html_lines.append("</code></pre>")
            else:
                in_code_block = True
                lang = stripped[3:].strip() or "text"
                html_lines.append(f'<pre><code class="language-{lang}">')
            continue

        if in_code_block:
            html_lines.append(line)
            continue

        if stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith(("- ", "* ")):
            html_lines.append(f"<li>{stripped[2:]}</li>")
        elif "[" in stripped and "](" in stripped:
            line = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', line)
            html_lines.append(f"<p>{line}</p>")
        elif "`" in stripped:
            line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
            html_lines.append(f"<p>{line}</p>")
        elif not stripped:
            html_lines.append("<br/>")
        else:
            html_lines.append(f"<p>{line}</p>")

    return "\n".join(html_lines)


def _looks_like_markdown(text: str) -> bool:
    """Heuristic to decide whether *text* looks like Markdown."""
    markers = ("# ", "## ", "### ", "- ", "* ", "```", "[", "](", "**", "__")
    return any(marker in text for marker in markers)


def _xml_local_name(tag: str) -> str:
    """Return the local XML tag name without namespace."""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


STRUCTURED_PREVIEW_MAX_BYTES = 256_000
STRUCTURED_XLSX_PREVIEW_ROWS = 5


def get_structured_preview_data(
    file_path: str,
    content: str | None = None,
    *,
    max_bytes: int = STRUCTURED_PREVIEW_MAX_BYTES,
) -> dict[str, Any]:
    """Return lightweight structured preview data for structured file formats."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".eml":
        return _structured_eml_preview(file_path, max_bytes=max_bytes)
    if suffix == ".epub":
        return _structured_epub_preview(file_path, max_bytes=max_bytes)
    if suffix == ".pdf":
        return _structured_pdf_preview(file_path, content, max_bytes=max_bytes)
    if suffix in {".docx", ".docm"}:
        return _structured_openxml_document_preview(file_path)
    if suffix in {".pptx", ".pptm"}:
        return _structured_presentation_preview(file_path)
    if content is None:
        content = _read_file_content(file_path, max_bytes=max_bytes)
    elif len(content) > max_bytes:
        content = content[:max_bytes]
    if not content:
        return {}
    if suffix in {".json", ".geojson", ".jsonc"}:
        return _structured_json_preview(file_path, content, max_bytes=max_bytes)
    if suffix in {".yaml", ".yml", ".toml"}:
        return _structured_text_preview(file_path, content, max_bytes=max_bytes)
    if suffix in {".html", ".htm", ".xhtml"}:
        return _structured_markup_preview(file_path, content, max_bytes=max_bytes)
    if suffix in {".xml", ".xsd", ".xsl", ".xslt"}:
        return _structured_xml_preview(file_path, content, max_bytes=max_bytes)
    if suffix in {".csv", ".tsv"}:
        return _structured_table_preview(file_path, content, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix in {".xlsx", ".xlsm"}:
        return _structured_xlsx_preview(file_path)
    if suffix == ".ods":
        return _structured_odf_preview(file_path)
    if suffix == ".ipynb":
        return _structured_notebook_preview(file_path, content)
    if any(suffix == candidate or Path(file_path).name.lower().endswith(candidate) for candidate in ARCHIVE_CONVERTED_SUFFIXES):
        return _structured_archive_preview(file_path)
    return {}


def get_structured_preview_markdown(
    file_path: str,
    content: str | None = None,
    *,
    max_bytes: int = STRUCTURED_PREVIEW_MAX_BYTES,
) -> str | None:
    """Return lightweight markdown for structured previews where available."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".eml":
        return _convert_eml_to_markdown(file_path)
    if suffix == ".epub":
        return _convert_epub_to_markdown(file_path)
    if suffix == ".pdf":
        return _convert_pdf_to_markdown(file_path)
    if suffix in {".docx", ".docm"}:
        return _convert_openxml_to_markdown(file_path)
    if suffix in {".json", ".geojson", ".jsonc", ".yaml", ".yml", ".toml", ".html", ".htm", ".xhtml", ".xml", ".xsd", ".xsl", ".xslt"}:
        if content is None:
            content = _read_file_content(file_path, max_bytes=max_bytes)
        elif len(content) > max_bytes:
            content = content[:max_bytes]
        if not content:
            return None
        structured = get_structured_preview_data(file_path, content, max_bytes=max_bytes)
        preview_content = str(structured.get("content") or "").strip()
        return preview_content or content
    if suffix in {".xlsx", ".xlsm"}:
        markdown, _structured = _xlsx_preview_summary(file_path)
        return markdown
    if suffix == ".ods":
        markdown, _structured = _odf_preview_summary(file_path)
        return markdown
    if suffix in {".pptx", ".pptm"}:
        markdown, _structured = _openxml_presentation_preview(file_path)
        return markdown
    if any(suffix == candidate or Path(file_path).name.lower().endswith(candidate) for candidate in ARCHIVE_CONVERTED_SUFFIXES):
        return _convert_archive_to_markdown(file_path)
    if suffix in {".csv", ".tsv"}:
        if content is None:
            content = _read_file_content(file_path, max_bytes=max_bytes)
        elif len(content) > max_bytes:
            content = content[:max_bytes]
        if not content:
            return None
        delimiter = "\t" if suffix == ".tsv" else ","
        return _structured_table_markdown(content, delimiter=delimiter)
    return None


def _structured_preview_metadata(file_path: str, content: str | None, language: str | None) -> dict[str, Any]:
    """Extract lightweight structured preview metadata for table/notebook-like files."""
    return get_structured_preview_data(file_path, content)


def _structured_eml_preview(file_path: str, *, max_bytes: int) -> dict[str, Any]:
    markdown = _convert_eml_to_markdown(file_path)
    if markdown is None:
        return {}
    try:
        with Path(file_path).open("rb") as handle:
            message = BytesParser(policy=policy.default).parse(handle)
    except Exception:
        return {}
    subject = _normalize_preview_text(str(message.get("subject", "") or ""))
    sender = _normalize_preview_text(str(message.get("from", "") or ""))
    to = _normalize_preview_text(str(message.get("to", "") or ""))
    cc = _normalize_preview_text(str(message.get("cc", "") or ""))
    date = _normalize_preview_text(str(message.get("date", "") or ""))
    attachments = list(message.iter_attachments()) if hasattr(message, "iter_attachments") else []
    content = markdown if len(markdown) <= max_bytes else markdown[:max_bytes].rstrip()
    return {
        "kind": "document",
        "format": "eml",
        "fileName": Path(file_path).name,
        "subject": subject or None,
        "from": sender or None,
        "to": to or None,
        "cc": cc or None,
        "date": date or None,
        "attachmentCount": len(attachments),
        "content": content,
        "truncated": len(markdown) > max_bytes,
    }


def _structured_epub_preview(file_path: str, *, max_bytes: int) -> dict[str, Any]:
    preview = _epub_preview_data(file_path)
    if not preview:
        return {}
    content = str(preview.get("content") or "").strip()
    if len(content) > max_bytes:
        content = content[:max_bytes].rstrip()
        truncated = True
    else:
        truncated = bool(preview.get("truncated"))
    result: dict[str, Any] = {
        "kind": "document",
        "format": "epub",
        "fileName": Path(file_path).name,
        "title": preview.get("title"),
        "sectionCount": preview.get("sectionCount"),
        "manifestCount": preview.get("manifestCount"),
        "content": content,
        "truncated": truncated,
    }
    if preview.get("chapters"):
        result["chapters"] = preview["chapters"]
    return result


def _structured_json_preview(file_path: str, content: str, *, max_bytes: int) -> dict[str, Any]:
    suffix = Path(file_path).suffix.lower()
    parsed: Any
    try:
        parsed = json.loads(content)
    except Exception:
        return _structured_text_preview(file_path, content, max_bytes=max_bytes)
    return _structured_serialized_preview(
        parsed,
        file_path=file_path,
        format_name="json" if suffix != ".geojson" else "geojson",
        kind="structured-text",
        max_bytes=max_bytes,
        extra={
            "topLevelType": "object" if isinstance(parsed, dict) else "array" if isinstance(parsed, list) else type(parsed).__name__,
            "keyCount": len(parsed) if isinstance(parsed, dict) else None,
            "itemCount": len(parsed) if isinstance(parsed, list) else None,
        },
    )


def _structured_text_preview(file_path: str, content: str, *, max_bytes: int) -> dict[str, Any]:
    suffix = Path(file_path).suffix.lower()
    format_name = suffix.lstrip(".") or "text"
    if suffix == ".toml":
        try:
            parsed = tomllib.loads(content)
        except Exception:
            parsed = None
        if parsed is not None:
            return _structured_serialized_preview(
                parsed,
                file_path=file_path,
                format_name="toml",
                kind="structured-text",
                max_bytes=max_bytes,
                extra={
                    "topLevelType": "object" if isinstance(parsed, dict) else type(parsed).__name__,
                    "keyCount": len(parsed) if isinstance(parsed, dict) else None,
                },
            )
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]

            parsed = yaml.safe_load(content)
        except Exception:
            parsed = None
        if parsed is not None:
            return _structured_serialized_preview(
                parsed,
                file_path=file_path,
                format_name="yaml" if suffix == ".yaml" else "yml",
                kind="structured-text",
                max_bytes=max_bytes,
                extra={
                    "topLevelType": "object" if isinstance(parsed, dict) else "array" if isinstance(parsed, list) else type(parsed).__name__,
                    "keyCount": len(parsed) if isinstance(parsed, dict) else None,
                    "itemCount": len(parsed) if isinstance(parsed, list) else None,
                },
            )
    return _structured_serialized_preview(
        content,
        file_path=file_path,
        format_name=format_name,
        kind="structured-text",
        max_bytes=max_bytes,
        extra={},
        raw_text=True,
    )


def _structured_markup_preview(file_path: str, content: str, *, max_bytes: int) -> dict[str, Any]:
    parsed = _extract_html_outline(content)
    if parsed:
        return _structured_serialized_preview(
            parsed["content"],
            file_path=file_path,
            format_name=parsed["format"],
            kind="markup",
            max_bytes=max_bytes,
            extra=parsed["extra"],
            raw_text=True,
        )
    return _structured_serialized_preview(
        content,
        file_path=file_path,
        format_name=Path(file_path).suffix.lower().lstrip(".") or "markup",
        kind="markup",
        max_bytes=max_bytes,
        extra={},
        raw_text=True,
    )


def _structured_xml_preview(file_path: str, content: str, *, max_bytes: int) -> dict[str, Any]:
    try:
        root = ET.fromstring(content)
    except Exception:
        return _structured_markup_preview(file_path, content, max_bytes=max_bytes)
    lines: list[str] = []
    _append_xml_outline(lines, root, depth=0, max_items=24)
    outline = "\n".join(lines).strip()
    if not outline:
        outline = content.strip()
    return _structured_serialized_preview(
        outline,
        file_path=file_path,
        format_name="xml",
        kind="markup",
        max_bytes=max_bytes,
        extra={
            "rootTag": _xml_local_name(root.tag),
            "tagCount": _count_xml_tags(root),
        },
        raw_text=True,
    )


def _structured_serialized_preview(
    value: Any,
    *,
    file_path: str,
    format_name: str,
    kind: str,
    max_bytes: int,
    extra: dict[str, Any],
    raw_text: bool = False,
) -> dict[str, Any]:
    if raw_text:
        content = str(value or "").strip()
        if len(content) > max_bytes:
            content = content[:max_bytes].rstrip()
            truncated = True
        else:
            truncated = False
    else:
        try:
            content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            content = str(value)
        truncated = len(content) > max_bytes
        if truncated:
            content = content[:max_bytes].rstrip()
    if not content:
        content = str(value)
    preview: dict[str, Any] = {
        "kind": kind,
        "format": format_name,
        "content": content,
        "truncated": truncated,
        "fileName": Path(file_path).name,
    }
    for key, val in extra.items():
        if val is not None:
            preview[key] = val
    return preview


class _HtmlOutlineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.items: list[tuple[str, str]] = []
        self._current_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"title", "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code"}:
            self._flush_current()
            self._current_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._current_tag == tag:
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._current_tag is not None:
            self._buffer.append(data)

    def _flush_current(self) -> None:
        if self._current_tag is None:
            return
        text = _normalize_preview_text("".join(self._buffer))
        if text:
            if self._current_tag == "title":
                self.title = text
            else:
                self.items.append((self._current_tag, text))
        self._current_tag = None
        self._buffer = []


def _extract_html_outline(content: str) -> dict[str, Any] | None:
    parser = _HtmlOutlineParser()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        return None
    if not parser.title and not parser.items:
        return None
    lines: list[str] = []
    if parser.title:
        lines.append(f"# {parser.title}")
    for tag, text in parser.items[:20]:
        prefix = {
            "h1": "#",
            "h2": "##",
            "h3": "###",
            "h4": "####",
            "h5": "#####",
            "h6": "######",
            "p": "-",
            "li": "-",
            "pre": "```",
            "code": "`",
        }.get(tag, "-")
        if prefix.startswith("#"):
            lines.append(f"{prefix} {text}")
        elif prefix == "```":
            lines.append("```")
            lines.append(text)
            lines.append("```")
        elif prefix == "`":
            lines.append(f"- code: {text}")
        else:
            lines.append(f"- {text}")
    if not lines:
        return None
    return {
        "format": "html",
        "content": "\n".join(lines),
        "extra": {
            "title": parser.title,
            "tagCount": len(parser.items) + (1 if parser.title else 0),
        },
    }


def _append_xml_outline(lines: list[str], element: ET.Element, *, depth: int, max_items: int) -> None:
    if len(lines) >= max_items:
        return
    tag = _xml_local_name(element.tag)
    text = _normalize_preview_text("".join(element.itertext()))
    indent = "  " * depth
    if text:
        lines.append(f"{indent}<{tag}> {text[:120]}")
    else:
        lines.append(f"{indent}<{tag}>")
    for child in list(element)[:6]:
        if len(lines) >= max_items:
            break
        _append_xml_outline(lines, child, depth=depth + 1, max_items=max_items)


def _count_xml_tags(element: ET.Element) -> int:
    count = 1
    for child in element:
        count += _count_xml_tags(child)
    return count


def _normalize_preview_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _structured_table_markdown(content: str, *, delimiter: str) -> str | None:
    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    except Exception:
        return None
    rows: list[list[str]] = []
    header: list[str] | None = None
    for row_index, row in enumerate(reader):
        normalized_row = [str(cell).strip() for cell in row]
        if row_index == 0:
            header = normalized_row
            continue
        rows.append(normalized_row)
        if len(rows) >= STRUCTURED_XLSX_PREVIEW_ROWS:
            break
    if header is None:
        return None
    width = len(header)
    if width == 0:
        return None
    padded_rows = [
        row[:width] + [""] * max(0, width - len(row))
        for row in rows
    ]
    lines = [
        "| " + " | ".join(header[:width]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row[:width]) + " |" for row in padded_rows)
    return "\n".join(lines)


def _structured_table_preview(file_path: str, content: str | None, *, delimiter: str) -> dict[str, Any]:
    if not content:
        return {}
    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    except Exception:
        return {}
    header: list[str] | None = None
    sample_rows: list[list[str]] = []
    row_count = 0
    for row_index, row in enumerate(reader):
        if row_index == 0:
            header = [str(cell).strip() for cell in row]
            continue
        row_count += 1
        if header is None:
            continue
        if len(sample_rows) >= 5:
            continue
        normalized_row = [str(cell) for cell in row[: len(header)]]
        if len(normalized_row) < len(header):
            normalized_row.extend([""] * (len(header) - len(normalized_row)))
        sample_rows.append(normalized_row)
    if header is None:
        return {}
    rows = sample_rows[:5]
    return {
        "kind": "table",
        "format": "csv" if delimiter == "," else "tsv",
        "columns": header,
        "rows": rows,
        "headers": header,
        "rowCount": row_count,
        "columnCount": len(header),
        "sampleRows": rows,
        "truncated": row_count > len(rows),
    }


def _structured_notebook_preview(file_path: str, content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    try:
        notebook = json.loads(content)
    except Exception:
        return {}
    if not isinstance(notebook, dict):
        return {}
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return {}
    cell_summaries: list[dict[str, Any]] = []
    rendered_cells: list[dict[str, Any]] = []
    for index, cell in enumerate(cells[:6]):
        if not isinstance(cell, dict):
            continue
        source = cell.get("source") or []
        if isinstance(source, list):
            source_lines = [str(item).rstrip("\n") for item in source]
            source_text = "".join(source_lines)
        else:
            source_text = str(source)
            source_lines = source_text.splitlines()
        cell_type = str(cell.get("cell_type") or "unknown")
        outputs: list[Any] = []
        raw_outputs = cell.get("outputs")
        if isinstance(raw_outputs, list):
            outputs = raw_outputs
        output_texts = [json.dumps(output, ensure_ascii=False)[:180] for output in outputs if isinstance(output, (dict, list))]
        cell_summaries.append(
            {
                "cellType": cell_type,
                "sourcePreview": source_text[:180],
                "outputCount": len(outputs),
            }
        )
        rendered_cells.append(
            {
                "index": index,
                "cellType": cell_type,
                "source": source_lines[:12],
                "outputs": output_texts[:4],
            }
        )
    return {
        "kind": "notebook",
        "format": "ipynb",
        "cells": rendered_cells,
        "cellCount": len(cells),
        "cellSummaries": cell_summaries,
        "truncated": len(cells) > len(rendered_cells),
    }


def _structured_xlsx_preview(file_path: str) -> dict[str, Any]:
    _, structured = _xlsx_preview_summary(file_path)
    return structured


def _structured_odf_preview(file_path: str) -> dict[str, Any]:
    _, structured = _odf_preview_summary(file_path)
    return structured


def _structured_presentation_preview(file_path: str) -> dict[str, Any]:
    _, structured = _openxml_presentation_preview(file_path)
    return structured


def _structured_openxml_document_preview(file_path: str) -> dict[str, Any]:
    """Extract a lightweight structured document preview from DOCX/DOCM packages."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in {".docx", ".docm"} or not path.exists():
        return {}
    try:
        with zipfile.ZipFile(path) as archive:
            xml_data = archive.read("word/document.xml")
    except Exception:
        return {}
    try:
        root = ET.fromstring(xml_data)
    except Exception:
        return {}

    paragraphs: list[str] = []
    for element in root.iter():
        if _xml_local_name(element.tag) != "p":
            continue
        text_parts = [
            str(child.text or "")
            for child in element.iter()
            if _xml_local_name(child.tag) == "t" and str(child.text or "").strip()
        ]
        paragraph = "".join(text_parts).strip()
        if paragraph:
            paragraphs.append(paragraph)
    if not paragraphs:
        return {}

    preview_content = "\n\n".join(paragraphs)
    return {
        "kind": "document",
        "format": suffix.lstrip("."),
        "fileName": path.name,
        "title": path.name,
        "paragraphCount": len(paragraphs),
        "content": preview_content,
        "truncated": False,
    }


def _structured_pdf_preview(file_path: str, content: str | None, *, max_bytes: int) -> dict[str, Any]:
    """Extract lightweight page metadata for PDF previews."""
    path = Path(file_path)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return {}
    if content is None:
        content = _convert_pdf_to_markdown(file_path)
    if not content:
        return {}
    truncated = len(content) > max_bytes
    if truncated:
        content = content[:max_bytes].rstrip()
    page_count: int | None = None
    try:
        import fitz  # type: ignore[import-not-found]

        document = fitz.open(file_path)
        page_count = len(document)
        document.close()
    except Exception:
        page_count = None
    result: dict[str, Any] = {
        "kind": "document",
        "format": "pdf",
        "fileName": path.name,
        "title": path.name,
        "content": content,
        "truncated": truncated,
    }
    if page_count is not None:
        result["pageCount"] = page_count
    else:
        fallback_page_count = _count_pdf_pages_from_bytes(path)
        if fallback_page_count is not None:
            result["pageCount"] = fallback_page_count
    return result


def _count_pdf_pages_from_bytes(path: Path) -> int | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    matches = re.findall(rb"/Type\s*/Page\b", data)
    if not matches:
        return None
    return len(matches)


def _structured_archive_preview(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    lowered_name = path.name.lower()
    if lowered_name.endswith(".zip") and zipfile.is_zipfile(path):
        entries = _zip_archive_entries(path)
        archive_format = "zip"
    elif any(lowered_name.endswith(suffix) for suffix in ARCHIVE_CONVERTED_SUFFIXES if suffix != ".zip") and tarfile.is_tarfile(path):
        entries = _tar_archive_entries(path)
        archive_format = "tar"
    else:
        return {}
    preview_entries = [
        {
            "path": str(entry.get("name") or ""),
            "kind": str(entry.get("entry_kind") or "file"),
            "sizeBytes": int(entry.get("size") or 0),
            "linkTarget": str(entry.get("link_target") or ""),
        }
        for entry in entries[:24]
    ]
    return {
        "kind": "archive",
        "format": archive_format,
        "entryCount": len(entries),
        "previewEntries": preview_entries,
        "truncated": len(entries) > len(preview_entries),
    }


def _zip_archive_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o777777
            entry_kind = "directory" if info.is_dir() else "file"
            if mode and stat.S_IFMT(mode) == stat.S_IFLNK:
                entry_kind = "symlink"
            entries.append(
                {
                    "name": info.filename,
                    "entry_kind": entry_kind,
                    "size": int(info.file_size or 0),
                    "link_target": "",
                }
            )
    return entries


def _tar_archive_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with tarfile.open(path) as archive:
        for info in archive.getmembers():
            entry_kind = "other"
            if info.isdir():
                entry_kind = "directory"
            elif info.issym():
                entry_kind = "symlink"
            elif info.islnk():
                entry_kind = "hardlink"
            elif info.isfile():
                entry_kind = "file"
            entries.append(
                {
                    "name": info.name,
                    "entry_kind": entry_kind,
                    "size": int(info.size or 0),
                    "link_target": getattr(info, "linkname", "") or "",
                }
            )
    return entries


def _convert_xlsx_to_markdown(file_path: str) -> str | None:
    markdown, _structured = _xlsx_preview_summary(file_path)
    return markdown


def _openxml_presentation_preview(file_path: str) -> tuple[str | None, dict[str, Any]]:
    """Extract a lightweight markdown outline and structured metadata from PPTX/PPTM."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix not in {".pptx", ".pptm"} or not path.exists():
        return None, {}
    try:
        with zipfile.ZipFile(path) as archive:
            slide_paths = sorted(
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/") and name.endswith(".xml")
            )
            if not slide_paths:
                return None, {}

            outline_lines: list[str] = [f"# {path.name}"]
            slide_summaries: list[dict[str, Any]] = []
            for index, slide_path in enumerate(slide_paths[:8], start=1):
                try:
                    slide_xml = archive.read(slide_path)
                except KeyError:
                    continue
                try:
                    root = ET.fromstring(slide_xml)
                except Exception:
                    continue
                paragraphs: list[str] = []
                for element in root.iter():
                    if _xml_local_name(element.tag) != "p":
                        continue
                    text_parts = [
                        str(child.text or "")
                        for child in element.iter()
                        if _xml_local_name(child.tag) == "t" and str(child.text or "").strip()
                    ]
                    paragraph = "".join(text_parts).strip()
                    if paragraph:
                        paragraphs.append(paragraph)
                if not paragraphs:
                    continue
                outline_lines.append(f"## Slide {index}")
                outline_lines.extend(paragraphs)
                slide_summaries.append(
                    {
                        "index": index - 1,
                        "title": f"Slide {index}",
                        "paragraphCount": len(paragraphs),
                        "preview": "\n\n".join(paragraphs[:6])[:240],
                    }
                )

            if len(outline_lines) <= 1:
                return None, {}
            markdown = "\n\n".join(line for line in outline_lines if line.strip())
            return markdown, {
                "kind": "document",
                "format": suffix.lstrip("."),
                "fileName": path.name,
                "title": path.name,
                "sectionCount": len(slide_summaries),
                "content": markdown,
                "slides": slide_summaries,
                "truncated": len(slide_paths) > len(slide_summaries),
            }
    except Exception:
        return None, {}


def _xlsx_preview_summary(file_path: str) -> tuple[str | None, dict[str, Any]]:
    """Generate markdown and structured preview for XLSX files.

    Attempts MarkItDown first for richer output, falls back to
    custom XML parsing.
    """
    # Try MarkItDown first - provides richer output
    markitdown_result = _convert_with_markitdown(file_path)
    if markitdown_result:
        # MarkItDown returns full markdown, but we still want structured data
        path = Path(file_path)
        structured = _structured_xlsx_preview(file_path)
        if structured:
            return markitdown_result, structured
        # Return markitdown result with basic metadata
        return markitdown_result, {
            "kind": "table",
            "format": "xlsx",
            "fileName": path.name,
            "source": "markitdown",
        }

    path = Path(file_path)
    if not path.exists():
        return None, {}
    try:
        with zipfile.ZipFile(path) as archive:
            workbook_sheet = _xlsx_first_sheet(archive)
            if workbook_sheet is None:
                return None, {}
            sheet_name, sheet_path, sheet_count = workbook_sheet
            row_count, max_column, sample_row_maps, needed_shared_string_indices = _xlsx_collect_sheet_preview(
                archive,
                sheet_path,
                max_preview_rows=STRUCTURED_XLSX_PREVIEW_ROWS,
            )
            shared_strings = _xlsx_load_shared_strings(archive, needed_shared_string_indices)
    except Exception:
        return None, {}

    if row_count == 0 or not sample_row_maps:
        return None, {}

    resolved_rows = _xlsx_resolve_preview_rows(
        sample_row_maps,
        shared_strings,
        column_count=max_column,
    )
    if not resolved_rows:
        return None, {}
    headers = [str(cell).strip() for cell in resolved_rows[0]]
    data_rows = [list(row) for row in resolved_rows[1:]]
    if not headers:
        return None, {}
    preview_markdown = _xlsx_rows_to_markdown(sheet_name, headers, data_rows)
    return preview_markdown, {
        "kind": "table",
        "format": "xlsx",
        "sheetName": sheet_name,
        "sheetCount": sheet_count,
        "columns": headers,
        "rows": data_rows,
        "headers": headers,
        "rowCount": max(0, row_count - 1),
        "columnCount": max(max_column, len(headers)),
        "sampleRows": data_rows,
        "truncated": row_count - 1 > len(data_rows),
    }


def _odf_preview_summary(file_path: str) -> tuple[str | None, dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        return None, {}
    root = _odf_content_root(file_path)
    if root is None:
        return None, {}
    markdown, structured = _odf_spreadsheet_preview(root, path.name)
    return markdown, structured


def _xlsx_first_sheet(archive: zipfile.ZipFile) -> tuple[str, str, int] | None:
    try:
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except Exception:
        return None
    rel_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    rels = {
        str(rel.attrib.get("Id") or ""): str(rel.attrib.get("Target") or "")
        for rel in rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
        if str(rel.attrib.get("Id") or "") and str(rel.attrib.get("Target") or "")
        and str(rel.attrib.get("TargetMode") or "").lower() != "external"
    }
    sheets = workbook_root.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")
    if not sheets:
        return None
    first_sheet = sheets[0]
    sheet_name = str(first_sheet.attrib.get("name") or "Sheet1")
    rel_id = str(first_sheet.attrib.get(f"{rel_namespace}id") or "")
    if not rel_id:
        return None
    target = rels.get(rel_id, "")
    if not target:
        return None
    normalized_target = _xlsx_normalize_target_path(target)
    return sheet_name, normalized_target, len(sheets)


def _xlsx_normalize_target_path(target: str) -> str:
    cleaned = target.lstrip("/")
    if cleaned.startswith("xl/"):
        return posixpath.normpath(cleaned)
    return posixpath.normpath(posixpath.join("xl", cleaned))


def _xlsx_collect_sheet_preview(
    archive: zipfile.ZipFile,
    sheet_path: str,
    *,
    max_preview_rows: int,
) -> tuple[int, int, list[dict[int, tuple[str, str | int]]], set[int]]:
    sample_row_maps: list[dict[int, tuple[str, str | int]]] = []
    needed_shared_string_indices: set[int] = set()
    row_count = 0
    max_column = 0
    # Keep xlsx previews bounded: store the header plus the requested data rows,
    # then read one extra row only to detect whether the preview is truncated.
    sample_limit = max_preview_rows + 1
    scan_limit = sample_limit + 1
    try:
        with archive.open(sheet_path) as handle:
            for _event, elem in ET.iterparse(handle, events=("end",)):
                if _xlsx_local_name(elem.tag) != "row":
                    continue
                row_count += 1
                row_map: dict[int, tuple[str, str | int]] = {}
                for cell in elem:
                    if _xlsx_local_name(cell.tag) != "c":
                        continue
                    column_index = _xlsx_column_index(str(cell.attrib.get("r") or ""))
                    if column_index <= 0:
                        continue
                    if column_index > max_column:
                        max_column = column_index
                    kind, value = _xlsx_cell_value(cell)
                    if kind == "shared_index":
                        row_map[column_index] = ("shared", value)
                        needed_shared_string_indices.add(int(value))
                    else:
                        row_map[column_index] = ("text", str(value))
                if row_count <= sample_limit:
                    sample_row_maps.append(row_map)
                if row_count >= scan_limit:
                    break
                elem.clear()
    except Exception:
        return 0, 0, [], set()
    return row_count, max_column, sample_row_maps, needed_shared_string_indices


def _xlsx_load_shared_strings(archive: zipfile.ZipFile, needed_indices: set[int]) -> dict[int, str]:
    if not needed_indices:
        return {}
    try:
        with archive.open("xl/sharedStrings.xml") as handle:
            result: dict[int, str] = {}
            current_index = -1
            for _event, elem in ET.iterparse(handle, events=("end",)):
                if _xlsx_local_name(elem.tag) != "si":
                    continue
                current_index += 1
                if current_index in needed_indices:
                    result[current_index] = "".join(elem.itertext())
                    if len(result) >= len(needed_indices):
                        break
                elem.clear()
            return result
    except KeyError:
        return {}
    except Exception:
        return {}


def _xlsx_resolve_preview_rows(
    sample_row_maps: list[dict[int, tuple[str, str | int]]],
    shared_strings: dict[int, str],
    *,
    column_count: int,
) -> list[list[str]]:
    resolved_rows: list[list[str]] = []
    width = max(0, column_count)
    for row_map in sample_row_maps:
        row = [""] * width
        for column_index, (kind, value) in row_map.items():
            resolved_value = ""
            if kind == "shared":
                resolved_value = shared_strings.get(int(value), "")
            else:
                resolved_value = str(value)
            position = column_index - 1
            if 0 <= position < width:
                row[position] = resolved_value
        resolved_rows.append(row)
    return resolved_rows


def _xlsx_rows_to_markdown(sheet_name: str, headers: list[str], sample_rows: list[list[str]]) -> str | None:
    width = len(headers)
    if width == 0:
        return None
    normalized_headers = [header if header else f"Column {index + 1}" for index, header in enumerate(headers[:width])]
    lines = [f"### {sheet_name}", ""]
    lines.append("| " + " | ".join(normalized_headers) + " |")
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in sample_rows[:STRUCTURED_XLSX_PREVIEW_ROWS]:
        padded = row[:width] + [""] * max(0, width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
    return "\n".join(lines)


def _xlsx_cell_value(cell: ET.Element) -> tuple[str, str | int]:
    cell_type = str(cell.attrib.get("t") or "")
    if cell_type == "s":
        shared_index_text = cell.findtext("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v") or "0"
        try:
            return "shared_index", int(shared_index_text)
        except ValueError:
            return "text", shared_index_text
    if cell_type == "inlineStr":
        inline = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
        if inline is None:
            return "text", ""
        return "text", "".join(inline.itertext())
    if cell_type == "b":
        value = cell.findtext("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v") or "0"
        return "text", "TRUE" if value.strip() == "1" else "FALSE"
    value = cell.findtext("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
    if value is not None:
        return "text", value
    return "text", "".join(cell.itertext())


def _xlsx_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xlsx_column_index(cell_ref: str) -> int:
    letters = []
    for character in cell_ref:
        if character.isalpha():
            letters.append(character.upper())
        else:
            break
    index = 0
    for character in letters:
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index


# Public helpers kept for external consumers

def get_supported_extensions() -> list[str]:
    """Return all supported file extensions."""
    return sorted(_EXTENSION_MAP.keys())


def get_tier_capabilities(tier: PreviewTier) -> list[str]:
    """Return extensions whose *best* tier equals *tier*."""
    return sorted(
        ext for ext, (best_tier, _lang, _native) in _EXTENSION_MAP.items() if best_tier == tier
    )


__all__ = [
    "PreviewService",
    "PreviewTier",
    "PreviewResult",
    "TIER_RICH",
    "TIER_CONVERTED",
    "TIER_METADATA",
    "get_structured_preview_data",
    "get_supported_extensions",
    "get_tier_capabilities",
]
