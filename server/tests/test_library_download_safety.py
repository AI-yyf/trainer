"""SEC-02: malicious archives must never escape the destination directory or
exhaust resources. The extractor is the last line of defense behind the HTTP
layer, so these guards are tested directly against hostile zip payloads."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.resources import library_downloads
from app.resources.library_downloads import DownloadError, _extract_repository_archive


def _zip(entries: dict[str, bytes], symlinks: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o120777 & 0xFFFF) << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def test_parent_traversal_is_refused_and_nothing_escapes(tmp_path: Path) -> None:
    destination = tmp_path / "repo"
    payload = _zip(
        {
            "repo-main/README.md": b"ok",
            "repo-main/../../escape.txt": b"pwned",
        }
    )
    with pytest.raises(DownloadError):
        _extract_repository_archive(payload, destination)
    assert not destination.exists()
    assert not (tmp_path.parent / "escape.txt").exists()


def test_absolute_paths_are_refused(tmp_path: Path) -> None:
    payload = _zip({"/tmp/trainer-escape.txt": b"pwned"})
    with pytest.raises(DownloadError):
        _extract_repository_archive(payload, tmp_path / "repo")
    assert not Path("/tmp/trainer-escape.txt").exists()


def test_symlink_entries_are_skipped(tmp_path: Path) -> None:
    payload = _zip(
        {"repo-main/README.md": b"ok"},
        symlinks=("repo-main/evil-link",),
    )
    destination = tmp_path / "repo"
    _extract_repository_archive(payload, destination)
    link = destination / "evil-link"
    assert not link.exists()
    assert (destination / "README.md").read_bytes() == b"ok"


def test_archive_entry_budget_is_enforced(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(library_downloads, "MAX_ARCHIVE_ENTRIES", 2)
    entries = {f"repo-main/file-{index}.txt": b"x" for index in range(5)}
    with pytest.raises(DownloadError):
        _extract_repository_archive(_zip(entries), tmp_path / "repo")
    assert not (tmp_path / "repo").exists()


def test_extracted_byte_budget_is_enforced(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(library_downloads, "MAX_EXTRACTED_BYTES", 16)
    entries = {
        "repo-main/a.txt": b"x" * 32,
        "repo-main/b.txt": b"y" * 32,
    }
    with pytest.raises(DownloadError):
        _extract_repository_archive(_zip(entries), tmp_path / "repo")
    assert not (tmp_path / "repo").exists()


def test_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    destination = tmp_path / "repo"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("mine", encoding="utf-8")
    payload = _zip({"repo-main/README.md": b"ok"})
    with pytest.raises(DownloadError):
        _extract_repository_archive(payload, destination)
    assert marker.read_text(encoding="utf-8") == "mine"
