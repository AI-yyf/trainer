"""On-disk store for canonical Markdown documents.

Layout (relative to the Trainer Library root)::

    resources/originals/<resource_id>/<original filename>
    resources/markdown/<resource_id>.md
    resources/markdown/assets/<resource_id>/<asset filename>

The original file is copied once and never modified; the Markdown document is
rewritten when the source, the parser version or the content hash changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .canonical import CanonicalDocument

CANONICAL_DIRNAME = "resources"
LIBRARY_DIRNAME = "Trainer Library"
ORIGINALS_DIRNAME = "originals"
MARKDOWN_DIRNAME = "markdown"
ASSETS_DIRNAME = "assets"


@dataclass(slots=True)
class CanonicalArtifact:
    """Resolved locations of one canonical artifact set."""

    markdown_path: Path
    markdown_relative: str
    original_path: Path | None
    original_relative: str | None
    assets_dir: Path
    created: bool


def library_root(workspace_root: Path) -> Path:
    return workspace_root / LIBRARY_DIRNAME


def canonical_root(workspace_root: Path) -> Path:
    return library_root(workspace_root) / CANONICAL_DIRNAME


def markdown_path_for(workspace_root: Path, resource_id: str) -> Path:
    return canonical_root(workspace_root) / MARKDOWN_DIRNAME / f"{_safe_segment(resource_id)}.md"


def original_dir_for(workspace_root: Path, resource_id: str) -> Path:
    return canonical_root(workspace_root) / ORIGINALS_DIRNAME / _safe_segment(resource_id)


def assets_dir_for(workspace_root: Path, resource_id: str) -> Path:
    return canonical_root(workspace_root) / MARKDOWN_DIRNAME / ASSETS_DIRNAME / _safe_segment(resource_id)


def workspace_relative(workspace_root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(workspace_root.resolve(strict=False)).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def write_canonical_artifact(
    workspace_root: Path,
    document: CanonicalDocument,
    *,
    original_bytes: bytes | None,
    original_filename: str,
) -> CanonicalArtifact:
    """Persist the Markdown document, its assets and the untouched original.

    Returns the resolved artifact locations. Existing files are replaced
    atomically so a reader never observes a half-written document.
    """

    resource_id = _safe_segment(document.resource_id)
    markdown_path = markdown_path_for(workspace_root, resource_id)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    assets_dir = assets_dir_for(workspace_root, resource_id)
    if document.assets:
        assets_dir.mkdir(parents=True, exist_ok=True)
        for asset in document.assets:
            target = assets_dir / _safe_asset_name(asset.filename)
            _write_bytes_atomic(target, asset.data)
    elif assets_dir.is_dir():
        # A previous parse may have produced assets that the new parse does not
        # reference; leaving them would make stale images reachable by URL.
        for child in assets_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)

    _write_bytes_atomic(markdown_path, document.render().encode("utf-8"))

    original_path: Path | None = None
    original_relative: str | None = None
    if original_bytes is not None:
        original_dir = original_dir_for(workspace_root, resource_id)
        original_dir.mkdir(parents=True, exist_ok=True)
        original_path = original_dir / _safe_original_name(original_filename)
        _write_bytes_atomic(original_path, original_bytes)
        original_relative = workspace_relative(workspace_root, original_path)

    return CanonicalArtifact(
        markdown_path=markdown_path,
        markdown_relative=workspace_relative(workspace_root, markdown_path),
        original_path=original_path,
        original_relative=original_relative,
        assets_dir=assets_dir,
        created=True,
    )


def read_canonical_markdown(workspace_root: Path, resource_id: str) -> str | None:
    path = markdown_path_for(workspace_root, resource_id)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", str(value or "")).strip(".-")
    return cleaned or "resource"


def _safe_asset_name(value: str) -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".")
    return name or "asset.bin"


def _safe_original_name(value: str) -> str:
    name = Path(str(value or "")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if not name or name in {".", ".."}:
        name = "source"
    if len(name) > 120:
        suffix = Path(name).suffix
        name = f"{Path(name).stem[: 120 - len(suffix)]}{suffix}"
    return name
