"""Artifact downloads for the Trainer Library folders.

Task two of the browser-capture lane: when a capture asks to ``download`` its
source, the original artifact — the PDF bytes or the whole GitHub repository —
is written into a real folder inside the opened workspace (``Trainer Library``
by default, or any workspace-relative ``target_dir``).

Everything here is deliberately non-destructive:

- an existing file with identical bytes is reused, never rewritten;
- a colliding different file is kept and the new artifact lands beside it under
  a content-suffixed name (the caller reports the actual path);
- a failed clone leaves nothing behind (the partial directory is removed) and
  falls back to the repository's default-branch ZIP archive;
- the ZIP is unpacked with explicit path-traversal and symlink protection.

Network access reuses the controlled fetch boundary for archives; ``git clone``
is the preferred transport for repositories and only ever talks to
``github.com`` (the repository URL is parsed and canonicalized first).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from app.network_fetch import ControlledFetchError, ControlledFetchResponse, fetch_url

GITHUB_REPOSITORY_API = "https://api.github.com/repos/{owner}/{repo}"
GITHUB_ARCHIVE_URL = "https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
GITHUB_ARCHIVE_HEAD_URL = "https://codeload.github.com/{owner}/{repo}/zip/HEAD"

GIT_CLONE_TIMEOUT_SECONDS = 300.0
GITHUB_ARCHIVE_MAX_BYTES = 64 * 1024 * 1024
GITHUB_ARCHIVE_TIMEOUT_SECONDS = 120.0
MAX_ARCHIVE_ENTRIES = 20_000
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024

_MAX_FILE_NAME_CHARS = 120
_CONTENT_SUFFIX_CHARS = 8
# Unicode word characters are kept so a CJK-titled paper keeps its title; path
# separators, colons and control characters are replaced.
_UNSAFE_FILE_NAME = re.compile(r"[^\w. ()\[\]-]+", re.UNICODE)


class DownloadError(RuntimeError):
    """A display-safe download failure carrying its copy key and HTTP status."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int,
        params: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.params = dict(params or {})


@dataclass(frozen=True, slots=True)
class ArtifactNote:
    """A user-visible note about a downloaded artifact (copy key + parameters)."""

    code: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SavedArtifact:
    """One artifact written into a library folder."""

    path: Path
    created: bool
    content_hash: str
    notes: tuple[ArtifactNote, ...] = ()


def safe_artifact_name(value: str, *, fallback: str, suffix: str = "") -> str:
    """Reduce a display title to a safe, readable file/folder name."""

    candidate = " ".join(str(value or "").split())
    candidate = _UNSAFE_FILE_NAME.sub("-", candidate).strip(" .-")
    if suffix and candidate.lower().endswith(suffix.lower()):
        candidate = candidate[: -len(suffix)]
    candidate = candidate[:_MAX_FILE_NAME_CHARS].rstrip(" .-")
    if not candidate:
        candidate = fallback
    return f"{candidate}{suffix}"


def _content_suffixed_name(name: str, content_hash: str) -> str:
    stem = Path(name).stem or name
    suffix = "".join(Path(name).suffixes)
    return f"{stem}-{content_hash[:_CONTENT_SUFFIX_CHARS]}{suffix}"


def _available_path(base: Path, *, content_hash: str) -> Path:
    """The base path when free, otherwise its content-suffixed sibling."""

    if not base.exists():
        return base
    candidate = base.with_name(_content_suffixed_name(base.name, content_hash))
    counter = 2
    while candidate.exists():
        stem = Path(_content_suffixed_name(base.name, content_hash)).stem
        candidate = candidate.with_name(f"{stem}-{counter}{base.suffix}")
        counter += 1
    return candidate


def _write_file_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def save_pdf_artifact(
    destination_dir: Path,
    *,
    file_name: str,
    content: bytes,
) -> SavedArtifact:
    """Write the captured PDF bytes into ``destination_dir`` (never overwrite)."""

    if not content:
        raise DownloadError("download_source_missing", status_code=409)
    content_hash = sha256(content).hexdigest()
    name = safe_artifact_name(file_name, fallback="captured-paper", suffix=".pdf")
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    destination = destination_dir / name
    notes: list[ArtifactNote] = []
    if destination.exists() and destination.is_file():
        try:
            existing = destination.read_bytes()
        except OSError as exc:
            raise DownloadError(
                "download_failed",
                status_code=500,
                params={"target": destination.name},
            ) from exc
        if existing == content:
            return SavedArtifact(
                path=destination,
                created=False,
                content_hash=content_hash,
                notes=(ArtifactNote("warning_existing_reused", {"path": destination.name}),),
            )
        original = destination
        destination = _available_path(destination, content_hash=content_hash)
        notes.append(
            ArtifactNote(
                "warning_collision_renamed",
                {"path": original.name, "saved_path": destination.name},
            )
        )
    elif destination.exists():
        raise DownloadError(
            "download_failed",
            status_code=409,
            params={"target": destination.name},
        )
    try:
        _write_file_atomically(destination, content)
    except OSError as exc:
        raise DownloadError(
            "download_failed",
            status_code=500,
            params={"target": destination.name},
        ) from exc
    return SavedArtifact(
        path=destination,
        created=True,
        content_hash=content_hash,
        notes=tuple(notes),
    )


def _git_executable() -> str | None:
    try:
        return shutil.which("git")
    except OSError:  # pragma: no cover - defensive: whose() only raises on bad PATH
        return None


def _clone_repository(clone_url: str, destination: Path) -> bool:
    """Clone ``--depth 1`` into ``destination``; never leaves a partial tree."""

    git = _git_executable()
    if not git:
        return False
    environment = {
        **os.environ,
        # Never let git block on an interactive credential prompt.
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return False
    try:
        result = subprocess.run(
            [
                git,
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--no-tags",
                clone_url,
                str(destination),
            ],
            capture_output=True,
            text=True,
            timeout=GIT_CLONE_TIMEOUT_SECONDS,
            env=environment,
            cwd=str(destination.parent),
        )
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(destination, ignore_errors=True)
        return False
    if result.returncode != 0:
        # A failed clone can leave a partially populated directory behind.
        shutil.rmtree(destination, ignore_errors=True)
        return False
    if not destination.is_dir():
        shutil.rmtree(destination, ignore_errors=True)
        return False
    return True


def _github_default_branch(owner: str, repo: str) -> str:
    """Best-effort default-branch lookup; the archive falls back to HEAD."""

    api_url = GITHUB_REPOSITORY_API.format(owner=owner, repo=repo)
    try:
        response = fetch_url(
            api_url,
            network_enabled=True,
            headers={"Accept": "application/vnd.github+json"},
            max_response_bytes=1024 * 1024,
            timeout_seconds=20.0,
        )
    except ControlledFetchError:
        return ""
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    branch = str(payload.get("default_branch") or "").strip()
    if not branch or not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch):
        return ""
    return branch


def _download_repository_archive(owner: str, repo: str) -> bytes:
    """Fetch the default-branch ZIP through the controlled fetch boundary."""

    candidates: list[str] = []
    default_branch = _github_default_branch(owner, repo)
    if default_branch:
        candidates.append(
            GITHUB_ARCHIVE_URL.format(owner=owner, repo=repo, ref=default_branch)
        )
    candidates.append(GITHUB_ARCHIVE_HEAD_URL.format(owner=owner, repo=repo))
    last_error: ControlledFetchError | None = None
    for url in dict.fromkeys(candidates):
        try:
            response: ControlledFetchResponse = fetch_url(
                url,
                network_enabled=True,
                max_response_bytes=GITHUB_ARCHIVE_MAX_BYTES,
                timeout_seconds=GITHUB_ARCHIVE_TIMEOUT_SECONDS,
            )
        except ControlledFetchError as exc:
            last_error = exc
            continue
        if response.body:
            return response.body
    raise DownloadError(
        "download_failed",
        status_code=502,
        params={"target": f"{owner}/{repo}"},
    ) from last_error


def _extract_repository_archive(body: bytes, destination: Path) -> None:
    """Unpack the single top-level archive folder into ``destination``.

    Extraction is fail-closed: absolute paths, ``..`` segments, symlink entries
    and oversized archives are refused, and nothing is left on disk when the
    extraction fails.
    """

    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise DownloadError(
            "download_failed",
            status_code=502,
            params={"target": destination.name},
        ) from exc
    with archive, tempfile.TemporaryDirectory(
        prefix=".trainer-archive-", dir=str(destination.parent)
    ) as staging_name:
        staging = Path(staging_name)
        total_bytes = 0
        extracted = 0
        for entry in archive.infolist():
            if extracted >= MAX_ARCHIVE_ENTRIES:
                raise DownloadError(
                    "download_failed",
                    status_code=502,
                    params={"target": destination.name},
                )
            name = entry.filename
            if not name or name.startswith("/") or "\\" in name or ":" in name:
                raise DownloadError(
                    "download_failed",
                    status_code=502,
                    params={"target": destination.name},
                )
            parts = [segment for segment in name.split("/") if segment not in {"", "."}]
            if any(segment == ".." for segment in parts):
                raise DownloadError(
                    "download_failed",
                    status_code=502,
                    params={"target": destination.name},
                )
            mode = entry.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                # Symlink entries are never materialized.
                continue
            total_bytes += int(entry.file_size)
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise DownloadError(
                    "download_failed",
                    status_code=502,
                    params={"target": destination.name},
                )
            if entry.is_dir():
                (staging.joinpath(*parts)).mkdir(parents=True, exist_ok=True)
                continue
            target = staging.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, open(target, "wb") as sink:
                shutil.copyfileobj(source, sink)
            extracted += 1
        roots = [item for item in staging.iterdir()] if staging.exists() else []
        if len(roots) != 1 or not roots[0].is_dir():
            raise DownloadError(
                "download_failed",
                status_code=502,
                params={"target": destination.name},
            )
        if destination.exists():
            raise DownloadError(
                "download_failed",
                status_code=409,
                params={"target": destination.name},
            )
        try:
            roots[0].replace(destination)
        except OSError as exc:
            raise DownloadError(
                "download_failed",
                status_code=500,
                params={"target": destination.name},
            ) from exc


def save_github_repository(
    destination_dir: Path,
    *,
    owner: str,
    repo: str,
    canonical_url: str,
    network_enabled: bool,
) -> SavedArtifact:
    """Materialize a whole repository into ``destination_dir/<repo>``.

    Preferred transport is ``git clone --depth 1``; when git is missing or the
    clone fails, the default-branch ZIP archive is downloaded and unpacked.
    """

    if not network_enabled:
        raise DownloadError("download_network_disabled", status_code=409)
    folder_name = safe_artifact_name(repo, fallback="repository")
    content_hash = sha256(canonical_url.encode("utf-8")).hexdigest()
    destination = destination_dir / folder_name
    notes: list[ArtifactNote] = []
    if destination.exists():
        if destination.is_dir() and not any(destination.iterdir()):
            # An empty leftover folder is Trainer's own; clone into it.
            destination.rmdir()
        else:
            original = destination
            destination = _available_path(destination, content_hash=content_hash)
            notes.append(
                ArtifactNote(
                    "warning_collision_renamed",
                    {"path": original.name, "saved_path": destination.name},
                )
            )
    destination_dir.mkdir(parents=True, exist_ok=True)
    if not _clone_repository(f"{canonical_url}.git", destination):
        notes.append(
            ArtifactNote("warning_clone_fallback")
            if _git_executable()
            else ArtifactNote("warning_git_unavailable")
        )
        body = _download_repository_archive(owner, repo)
        _extract_repository_archive(body, destination)
    return SavedArtifact(
        path=destination,
        created=True,
        content_hash=content_hash,
        notes=tuple(notes),
    )


def snapshot_bytes_for_pdf(resource_source: str | None, resource_sandbox_path: str | None) -> bytes:
    """Read the owned PDF snapshot bytes for a re-download of a deduped capture."""

    for candidate in (resource_sandbox_path, resource_source):
        raw = str(candidate or "").strip()
        if not raw or "://" in raw:
            continue
        path = Path(raw)
        try:
            if path.is_file():
                return path.read_bytes()
        except OSError:
            continue
    return b""


def decode_base64_content(content: str | None) -> bytes:
    """Decode the base64 payload a ``CapturedSource`` carries for binary kinds."""

    raw = str(content or "")
    if not raw:
        return b""
    try:
        return base64.b64decode(raw, validate=False)
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return b""


__all__ = [
    "ArtifactNote",
    "DownloadError",
    "GITHUB_ARCHIVE_MAX_BYTES",
    "SavedArtifact",
    "decode_base64_content",
    "safe_artifact_name",
    "save_github_repository",
    "save_pdf_artifact",
    "snapshot_bytes_for_pdf",
]
