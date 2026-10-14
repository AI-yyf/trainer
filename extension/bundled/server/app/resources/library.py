"""Trainer Library: real workspace folders for captures, downloads and groups.

The browser-capture lane can ask the sidecar to *download* the captured artifact
— the PDF bytes or the whole GitHub repository — into a real folder inside the
opened workspace. This module owns that folder lane:

- ``Trainer Library/`` under the workspace root is the default target and the
  management root of the library group tree;
- every path is validated through the existing ``WorkspaceAuthority`` (boundary
  check → ``target_outside_workspace`` 422; host-attested trust and remote
  fail-closed → ``library_not_writable`` 403);
- writes obey the existing six-level permission ladder: a new artifact is
  ``GENERATE`` (level 4), touching an existing artifact is ``WRITE``/``APPLY``
  (level 5), folder creation is ``MKDIR`` (``REORGANIZE``, level 3), renaming is
  ``RENAME`` and moving a folder to the library recycle bin is ``DELETE``
  (``DESTRUCTIVE``, level 6). The ladder, its map and the "Trainer library is a
  Trainer-owned local carrier" determination are exactly the ones the sandbox
  service already uses for library writes — nothing new is manufactured here;
- groups are real folders: ``GET /library/groups`` reports the tree under the
  management root with per-group resource counts, ``POST`` creates folders for
  real, rename moves them, and delete moves them into the library recycle bin
  (``Trainer Library/.trash/<timestamp>-<id>/…``), never a hard delete.

Download locations are recorded on the library resource itself
(``ResourceRecord.library_paths``, workspace-relative POSIX paths) so the group
counts, renames and trashes stay truthful for the resources that live in those
folders.
"""

from __future__ import annotations

import logging
import os
import posixpath
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..core.models import ResourceRecord
from ..workspace.authority import (
    OPERATION_PERMISSION_MAP,
    OperationRecord,
    OperationType,
    PermissionLevel,
    WorkspaceAuthority,
)
from .capture import parse_github_repo
from .library_copy import library_message
from .library_downloads import (
    ArtifactNote,
    DownloadError,
    SavedArtifact,
    decode_base64_content,
    safe_artifact_name,
    save_github_repository,
    save_pdf_artifact,
    snapshot_bytes_for_pdf,
)

logger = logging.getLogger(__name__)

LIBRARY_DIRECTORY_NAME = "Trainer Library"
LIBRARY_TRASH_DIRECTORY_NAME = ".trash"

MAX_LIBRARY_PATH_DEPTH = 6
MAX_LIBRARY_SEGMENT_CHARS = 60
MAX_LIBRARY_PATH_CHARS = 240

# Names Trainer keeps for its own storage; they can never become a library
# folder or a download target.
_RESERVED_LIBRARY_SEGMENTS = frozenset(
    {
        ".trainer",
        ".trainer-sandbox",
        ".git",
        "inline-resources",
        "sandbox",
    }
)


class LibraryError(RuntimeError):
    """A display-safe library failure carrying its copy key and HTTP mapping."""

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
        self.params = {key: str(value) for key, value in (params or {}).items()}

    def message(self, language: str | None) -> str:
        return library_message(self.code, language, **self.params)

    def as_detail(self, language: str | None) -> dict[str, str]:
        return {"code": self.code, "message": self.message(language)}


@dataclass(frozen=True, slots=True)
class LibraryDownload:
    """One downloaded artifact, expressed relative to the workspace root."""

    relative_path: str
    kind: str
    created: bool
    notes: tuple[ArtifactNote, ...] = ()


@dataclass(frozen=True, slots=True)
class LibraryGroupsSnapshot:
    """The real-folder group tree under the library management root."""

    managed_root: str
    exists: bool
    trash_root: str
    total_resource_count: int
    groups: list[dict[str, object]]


def normalize_library_relative_path(value: str) -> str:
    """Normalize a workspace-relative folder path into its POSIX identity.

    Raises ``LibraryError(invalid_target_dir)`` for absolute paths, ``..``
    traversal, hidden and reserved segments, or an over-long path.
    """

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise LibraryError("invalid_target_dir", status_code=422)
    if raw.startswith("/") or raw.startswith("~") or "://" in raw:
        raise LibraryError("invalid_target_dir", status_code=422)
    if len(raw) > MAX_LIBRARY_PATH_CHARS:
        raise LibraryError("invalid_target_dir", status_code=422)
    if any(ord(character) < 32 for character in raw):
        raise LibraryError("invalid_target_dir", status_code=422)
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        raise LibraryError("invalid_target_dir", status_code=422)
    segments = [segment.strip() for segment in raw.split("/") if segment.strip()]
    if not segments:
        raise LibraryError("invalid_target_dir", status_code=422)
    if len(segments) > MAX_LIBRARY_PATH_DEPTH:
        raise LibraryError("invalid_target_dir", status_code=422)
    normalized: list[str] = []
    for segment in segments:
        if segment in {".", ".."}:
            raise LibraryError("invalid_target_dir", status_code=422)
        if segment.startswith("."):
            raise LibraryError("invalid_target_dir", status_code=422)
        if len(segment) > MAX_LIBRARY_SEGMENT_CHARS:
            raise LibraryError("invalid_target_dir", status_code=422)
        if segment.casefold() in _RESERVED_LIBRARY_SEGMENTS:
            raise LibraryError("invalid_target_dir", status_code=422)
        normalized.append(segment)
    return "/".join(normalized)


def normalize_group_path(value: str) -> str:
    """Normalize a group path relative to the library management root.

    A leading ``Trainer Library/`` segment is accepted and normalized away so
    both ``Papers`` and ``Trainer Library/Papers`` name the same group.
    """

    raw = str(value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        raise LibraryError("group_missing_path", status_code=422)
    segments = [segment.strip() for segment in raw.split("/") if segment.strip()]
    if segments and segments[0].casefold() == LIBRARY_DIRECTORY_NAME.casefold():
        segments = segments[1:]
    if not segments:
        raise LibraryError("group_is_library_root", status_code=409)
    try:
        return normalize_library_relative_path("/".join(segments))
    except LibraryError as exc:
        raise LibraryError("group_invalid_path", status_code=422) from exc


class LibraryService:
    """Real-folder Trainer Library lane: downloads, groups and their bookkeeping."""

    def __init__(
        self,
        repository: Any,
        *,
        workspace_authority_resolver: Callable[[str], WorkspaceAuthority | None],
    ) -> None:
        self._repository = repository
        self._workspace_authority_resolver = workspace_authority_resolver
        self._carrier_authorities: dict[tuple[str, str], WorkspaceAuthority] = {}

    # ------------------------------------------------------------- authorities

    def _authority(self, workspace_id: str) -> WorkspaceAuthority:
        try:
            authority = self._workspace_authority_resolver(workspace_id)
        except Exception:  # pragma: no cover - resolver is runtime-owned
            logger.warning(
                "Library authority resolution failed for workspace %s.",
                workspace_id,
                exc_info=True,
            )
            authority = None
        if authority is None or not authority.has_active_workspace_root:
            raise LibraryError("library_root_unavailable", status_code=409)
        return authority

    @staticmethod
    def _require_writable_workspace(authority: WorkspaceAuthority) -> None:
        """Host-attested trust gate: untrusted and remote workspaces fail closed."""

        if authority.destructive_mutation_block_reason():
            raise LibraryError("library_not_writable", status_code=403)

    def workspace_root(self, workspace_id: str) -> Path:
        authority = self._authority(workspace_id)
        root = Path(str(authority.active_workspace_root)).expanduser().resolve(strict=False)
        return root

    def resolve_workspace_path(self, workspace_id: str, relative_path: str) -> Path | None:
        """Resolve a recorded workspace-relative library path back to disk."""

        text = str(relative_path or "").strip().replace("\\", "/").strip("/")
        if not text:
            return None
        workspace_root = self.workspace_root(workspace_id)
        candidate = workspace_root.joinpath(*text.split("/"))
        return candidate if self._is_within(candidate, workspace_root) else None

    def library_root(self, workspace_id: str, *, create: bool = False) -> Path:
        """The library management root: ``<workspace root>/Trainer Library``."""

        root = self.workspace_root(workspace_id) / LIBRARY_DIRECTORY_NAME
        if create and not root.is_dir():
            try:
                root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LibraryError(
                    "group_mutation_failed",
                    status_code=500,
                    params={"path": LIBRARY_DIRECTORY_NAME},
                ) from exc
        return root

    def _carrier_authority(self, workspace_id: str, library_root: Path) -> WorkspaceAuthority:
        """The Trainer-owned library carrier authority (same rule as the sandbox).

        The library folder is Trainer's own managed area inside a trusted local
        workspace; ``SandboxService._operation_authority`` already establishes
        that a Trainer-owned carrier may raise its own level to the operation
        minimum instead of blocking library writes on project permissions.
        """

        key = (workspace_id, str(library_root))
        carrier = self._carrier_authorities.get(key)
        if carrier is None or str(carrier.active_workspace_root or "") != str(library_root):
            carrier = WorkspaceAuthority(
                root_path=str(library_root),
                initial_permission=PermissionLevel.INSPECT,
            )
            carrier.set_workspace_context(workspace_trusted=True)
            self._carrier_authorities[key] = carrier
        return carrier

    def _authorize(
        self,
        workspace_id: str,
        library_root: Path,
        operation: str,
        path: Path,
        *,
        details: dict[str, object] | None = None,
    ) -> OperationRecord:
        """Run one library mutation through the six-level permission ladder."""

        required = OPERATION_PERMISSION_MAP.get(operation)
        if required is None:  # pragma: no cover - callers use known operations
            raise LibraryError("library_write_denied", status_code=403)
        carrier = self._carrier_authority(workspace_id, library_root)
        previous_level = carrier.permission_level
        if int(previous_level) < int(required):
            carrier.set_permission_level(required)
        try:
            allowed = carrier.can_perform(operation, path)
            record = (
                carrier.log_operation(
                    operation,
                    str(path),
                    "allowed",
                    details=dict(details or {}),
                )
                if allowed
                else None
            )
        finally:
            if int(previous_level) < int(required):
                carrier.set_permission_level(previous_level)
        if not allowed or record is None:
            raise LibraryError("library_write_denied", status_code=403)
        return record

    def authority_ledger(self, workspace_id: str) -> list[OperationRecord]:
        """Audit view of the library carrier operations (host diagnostics/tests)."""

        records: list[OperationRecord] = []
        for (candidate_workspace, _root), carrier in self._carrier_authorities.items():
            if candidate_workspace == workspace_id:
                records.extend(carrier.operation_ledger)
        return records

    # ---------------------------------------------------------------- targets

    def resolve_target_dir(
        self,
        workspace_id: str,
        target_dir: str | None,
        *,
        create: bool,
    ) -> tuple[Path, str]:
        """Resolve a workspace-relative download folder (defaults to the library root).

        Returns ``(absolute directory, workspace-relative POSIX path)``. The
        directory is validated through the workspace authority boundary before
        anything is created; when ``create`` is set the folder is created for
        real (``MKDIR`` on the permission ladder).
        """

        authority = self._authority(workspace_id)
        self._require_writable_workspace(authority)
        workspace_root = Path(str(authority.active_workspace_root)).expanduser().resolve(strict=False)
        raw = str(target_dir or "").strip()
        relative = (
            normalize_library_relative_path(raw) if raw else LIBRARY_DIRECTORY_NAME
        )
        candidate = workspace_root.joinpath(*relative.split("/"))
        try:
            normalized, is_within = authority.normalize_and_validate(candidate, allow_outside=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise LibraryError(
                "invalid_target_dir",
                status_code=422,
                params={"target_dir": relative},
            ) from exc
        if not is_within:
            raise LibraryError(
                "target_outside_workspace",
                status_code=422,
                params={"target_dir": relative},
            )
        if create:
            library_root = workspace_root / LIBRARY_DIRECTORY_NAME
            self._ensure_library_root(library_root)
            if not normalized.is_dir():
                self._authorize(
                    workspace_id,
                    library_root,
                    OperationType.MKDIR,
                    normalized,
                    details={"target_dir": relative},
                )
            try:
                normalized.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LibraryError(
                    "group_mutation_failed",
                    status_code=500,
                    params={"path": relative},
                ) from exc
        return normalized, relative

    def _ensure_library_root(self, library_root: Path) -> None:
        if library_root.is_dir():
            return
        try:
            library_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LibraryError(
                "group_mutation_failed",
                status_code=500,
                params={"path": LIBRARY_DIRECTORY_NAME},
            ) from exc

    # -------------------------------------------------------------- downloads

    def save_download(
        self,
        workspace_id: str,
        *,
        kind: str,
        url: str,
        title: str,
        target_dir: str | None,
        network_enabled: bool,
        content_base64: str | None = None,
        existing_resource: ResourceRecord | None = None,
    ) -> LibraryDownload:
        """Download the captured artifact into the target folder.

        ``content_base64`` carries the already-fetched PDF bytes of a fresh
        capture; ``existing_resource`` carries the owned snapshot when the
        capture deduped against an earlier one, so a PDF re-download never
        fetches the same file twice.
        """

        if kind not in {"pdf", "github_repo"}:
            raise LibraryError("download_kind_unsupported", status_code=422)
        if kind == "github_repo" and not network_enabled:
            # A repository can only be downloaded from the network; refuse
            # before creating any folder.
            raise LibraryError("download_network_disabled", status_code=409)
        directory, _target_relative = self.resolve_target_dir(
            workspace_id,
            target_dir,
            create=True,
        )
        library_root = self.library_root(workspace_id, create=True)
        try:
            discovered = self._write_artifact(
                workspace_id,
                library_root,
                directory,
                kind=kind,
                url=url,
                title=title,
                network_enabled=network_enabled,
                content_base64=content_base64,
                existing_resource=existing_resource,
            )
        except DownloadError as exc:
            raise LibraryError(exc.code, status_code=exc.status_code, params=exc.params) from exc
        workspace_root = self.workspace_root(workspace_id)
        relative_path = self._relative_to_workspace(discovered.path, workspace_root)
        return LibraryDownload(
            relative_path=relative_path,
            kind=kind,
            created=discovered.created,
            notes=discovered.notes,
        )

    def _write_artifact(
        self,
        workspace_id: str,
        library_root: Path,
        directory: Path,
        *,
        kind: str,
        url: str,
        title: str,
        network_enabled: bool,
        content_base64: str | None,
        existing_resource: ResourceRecord | None,
    ) -> SavedArtifact:
        if kind == "pdf":
            name = safe_artifact_name(
                self._pdf_artifact_title(title, url),
                fallback="captured-paper",
                suffix=".pdf",
            )
            intended = directory / name
            self._authorize(
                workspace_id,
                library_root,
                OperationType.GENERATE if not intended.exists() else OperationType.WRITE,
                intended,
                details={"kind": kind, "target": str(intended)},
            )
            content = decode_base64_content(content_base64)
            if not content and existing_resource is not None:
                content = snapshot_bytes_for_pdf(
                    existing_resource.source,
                    existing_resource.sandbox_path,
                )
            if not content:
                raise LibraryError("download_source_missing", status_code=409)
            artifact = save_pdf_artifact(directory, file_name=name, content=content)
            return artifact

        repository = parse_github_repo(url)
        if repository is None:
            raise LibraryError("download_kind_unsupported", status_code=422)
        owner, repo, canonical_url = repository
        intended = directory / safe_artifact_name(repo, fallback="repository")
        self._authorize(
            workspace_id,
            library_root,
            OperationType.GENERATE if not intended.exists() else OperationType.WRITE,
            intended,
            details={"kind": kind, "target": str(intended), "repository": canonical_url},
        )
        return save_github_repository(
            directory,
            owner=owner,
            repo=repo,
            canonical_url=canonical_url,
            network_enabled=network_enabled,
        )

    @staticmethod
    def _pdf_artifact_title(title: str, url: str) -> str:
        candidate = " ".join(str(title or "").split())
        if not candidate:
            candidate = Path(str(url or "").split("?")[0]).name or "captured-paper"
        return candidate

    @staticmethod
    def _relative_to_workspace(path: Path, workspace_root: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(workspace_root).as_posix()
        except ValueError:  # pragma: no cover - downloads are validated in-boundary
            return path.name

    # -------------------------------------------------- resource bookkeeping

    def remember_download(
        self,
        workspace_id: str,
        resource: ResourceRecord | None,
        download: LibraryDownload | None,
    ) -> ResourceRecord | None:
        """Record the downloaded folder on the resource (idempotent)."""

        if resource is None or download is None:
            return resource
        existing = [str(item) for item in (resource.library_paths or [])]
        if download.relative_path in existing:
            return resource
        updated = resource.model_copy(
            update={"library_paths": [*existing, download.relative_path]}
        )
        self._repository.save_resource(workspace_id, updated)
        return updated

    # ----------------------------------------------------------------- groups

    def list_groups(self, workspace_id: str) -> LibraryGroupsSnapshot:
        """Real folders under the management root with per-group resource counts."""

        self._authority(workspace_id)
        library_root = self.library_root(workspace_id, create=False)
        membership = self._resource_membership(workspace_id)
        managed_root = LIBRARY_DIRECTORY_NAME
        trash_root = f"{managed_root}/{LIBRARY_TRASH_DIRECTORY_NAME}"
        total = len(membership.get("", set()))
        if not library_root.is_dir():
            return LibraryGroupsSnapshot(
                managed_root=managed_root,
                exists=False,
                trash_root=trash_root,
                total_resource_count=total,
                groups=[],
            )
        groups = self._scan_groups(library_root, "", membership, depth=0)
        return LibraryGroupsSnapshot(
            managed_root=managed_root,
            exists=True,
            trash_root=trash_root,
            total_resource_count=total,
            groups=groups,
        )

    def _scan_groups(
        self,
        library_root: Path,
        relative: str,
        membership: dict[str, set[str]],
        *,
        depth: int,
    ) -> list[dict[str, object]]:
        if depth >= MAX_LIBRARY_PATH_DEPTH:
            return []
        base = library_root if not relative else library_root.joinpath(*relative.split("/"))
        try:
            entries = sorted(
                (entry for entry in os.scandir(base) if entry.is_dir(follow_symlinks=False)),
                key=lambda entry: entry.name.casefold(),
            )
        except OSError:
            return []
        nodes: list[dict[str, object]] = []
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name.casefold() in _RESERVED_LIBRARY_SEGMENTS:
                continue
            group_path = f"{relative}/{name}" if relative else name
            nodes.append(
                {
                    "path": group_path,
                    "name": name,
                    "workspace_path": f"{LIBRARY_DIRECTORY_NAME}/{group_path}",
                    "resource_count": len(membership.get(group_path, set())),
                    "children": self._scan_groups(
                        library_root,
                        group_path,
                        membership,
                        depth=depth + 1,
                    ),
                }
            )
        return nodes

    def _resource_membership(self, workspace_id: str) -> dict[str, set[str]]:
        """group path -> ids of library resources downloaded into it (incl. nested)."""

        membership: dict[str, set[str]] = {}
        prefix = f"{LIBRARY_DIRECTORY_NAME}/"
        for resource in self._repository.list_resources(workspace_id):
            for relative in getattr(resource, "library_paths", []) or []:
                text = str(relative or "").strip().replace("\\", "/").strip("/")
                if not text.startswith(prefix):
                    continue
                inner = text[len(prefix) :]
                if inner.startswith(f"{LIBRARY_TRASH_DIRECTORY_NAME}/"):
                    # Trashed folders are not library groups.
                    continue
                folder = posixpath.dirname(inner)
                target = f"{LIBRARY_DIRECTORY_NAME}/{folder}" if folder else LIBRARY_DIRECTORY_NAME
                segments = target.split("/")
                for depth in range(1, len(segments) + 1):
                    membership.setdefault("/".join(segments[1:depth]), set()).add(resource.id)
        return membership

    def create_group(self, workspace_id: str, path: str) -> dict[str, object]:
        group_path = normalize_group_path(path)
        authority = self._authority(workspace_id)
        self._require_writable_workspace(authority)
        library_root = self.library_root(workspace_id, create=True)
        target = library_root.joinpath(*group_path.split("/"))
        self._validate_group_target(authority, target, group_path)
        if target.exists() and not target.is_dir():
            raise LibraryError(
                "group_already_exists",
                status_code=409,
                params={"path": group_path},
            )
        existed = target.is_dir()
        if not existed:
            self._authorize(
                workspace_id,
                library_root,
                OperationType.MKDIR,
                target,
                details={"group": group_path},
            )
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LibraryError(
                    "group_mutation_failed",
                    status_code=500,
                    params={"path": group_path},
                ) from exc
        return {
            "workspace_id": workspace_id,
            "created": not existed,
            "managed_root": LIBRARY_DIRECTORY_NAME,
            "group": {
                "path": group_path,
                "name": group_path.rsplit("/", 1)[-1],
                "workspace_path": f"{LIBRARY_DIRECTORY_NAME}/{group_path}",
                "resource_count": len(self._resource_membership(workspace_id).get(group_path, set())),
            },
        }

    def rename_group(
        self,
        workspace_id: str,
        from_path: str,
        to_path: str,
    ) -> dict[str, object]:
        source_group = normalize_group_path(from_path)
        target_group = normalize_group_path(to_path)
        authority = self._authority(workspace_id)
        self._require_writable_workspace(authority)
        library_root = self.library_root(workspace_id, create=True)
        source = library_root.joinpath(*source_group.split("/"))
        target = library_root.joinpath(*target_group.split("/"))
        self._validate_group_target(authority, source, source_group)
        self._validate_group_target(authority, target, target_group)
        if not source.is_dir():
            raise LibraryError(
                "group_not_found",
                status_code=404,
                params={"path": source_group},
            )
        if target_group == source_group:
            return {
                "workspace_id": workspace_id,
                "renamed": False,
                "from": source_group,
                "to": target_group,
                "moved_resource_count": 0,
            }
        if target_group.startswith(f"{source_group}/"):
            raise LibraryError("group_rename_into_itself", status_code=422)
        if target.exists():
            raise LibraryError(
                "group_already_exists",
                status_code=409,
                params={"path": target_group},
            )
        moved_resources = self._resources_under(workspace_id, source_group)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._authorize(
            workspace_id,
            library_root,
            OperationType.RENAME,
            source,
            details={"from": source_group, "to": target_group},
        )
        try:
            source.rename(target)
        except OSError as exc:
            raise LibraryError(
                "group_mutation_failed",
                status_code=500,
                params={"path": source_group},
            ) from exc
        self._rewrite_moved_resource_paths(
            workspace_id,
            source_group,
            target_group,
            moved_resources,
            library_root=library_root,
        )
        return {
            "workspace_id": workspace_id,
            "renamed": True,
            "from": source_group,
            "to": target_group,
            "moved_resource_count": len(moved_resources),
        }

    def trash_group(self, workspace_id: str, path: str) -> dict[str, object]:
        """Move a group folder into the library recycle bin (never a hard delete)."""

        group_path = normalize_group_path(path)
        authority = self._authority(workspace_id)
        self._require_writable_workspace(authority)
        library_root = self.library_root(workspace_id, create=True)
        target = library_root.joinpath(*group_path.split("/"))
        self._validate_group_target(authority, target, group_path)
        if not target.is_dir():
            raise LibraryError(
                "group_not_found",
                status_code=404,
                params={"path": group_path},
            )
        moved_resources = self._resources_under(workspace_id, group_path)
        self._authorize(
            workspace_id,
            library_root,
            OperationType.DELETE,
            target,
            details={"group": group_path},
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        trash_dir = (
            library_root
            / LIBRARY_TRASH_DIRECTORY_NAME
            / f"{stamp}-{uuid4().hex[:8]}"
        )
        trashed = trash_dir.joinpath(*group_path.split("/"))
        try:
            trashed.parent.mkdir(parents=True, exist_ok=True)
            target.rename(trashed)
        except OSError as exc:
            raise LibraryError(
                "group_mutation_failed",
                status_code=500,
                params={"path": group_path},
            ) from exc
        trashed_group = f"{LIBRARY_TRASH_DIRECTORY_NAME}/{trash_dir.name}/{group_path}"
        self._rewrite_moved_resource_paths(
            workspace_id,
            group_path,
            trashed_group,
            moved_resources,
            library_root=library_root,
        )
        return {
            "workspace_id": workspace_id,
            "trashed": True,
            "group": group_path,
            "trash_path": f"{LIBRARY_DIRECTORY_NAME}/{trashed_group}",
            "moved_resource_count": len(moved_resources),
            "recoverable": True,
        }

    def _validate_group_target(
        self,
        authority: WorkspaceAuthority,
        target: Path,
        group_path: str,
    ) -> None:
        library_root = Path(str(authority.active_workspace_root)) / LIBRARY_DIRECTORY_NAME
        try:
            normalized, is_within = authority.normalize_and_validate(target, allow_outside=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise LibraryError("group_invalid_path", status_code=422) from exc
        if not is_within or not self._is_within(normalized, library_root):
            raise LibraryError(
                "group_invalid_path",
                status_code=422,
                params={"path": group_path},
            )

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except (ValueError, OSError):
            return False
        return True

    def _resources_under(self, workspace_id: str, group_path: str) -> list[ResourceRecord]:
        prefix = f"{LIBRARY_DIRECTORY_NAME}/{group_path}/"
        affected: list[ResourceRecord] = []
        for resource in self._repository.list_resources(workspace_id):
            for relative in getattr(resource, "library_paths", []) or []:
                text = str(relative or "").strip().replace("\\", "/").strip("/")
                if text.startswith(prefix):
                    affected.append(resource)
                    break
        return affected

    def _rewrite_moved_resource_paths(
        self,
        workspace_id: str,
        from_group: str,
        to_group: str,
        resources: list[ResourceRecord],
        *,
        library_root: Path,
    ) -> None:
        """Keep the recorded download locations truthful after a folder move."""

        if not resources:
            return
        from_prefix = f"{LIBRARY_DIRECTORY_NAME}/{from_group}/"
        to_prefix = f"{LIBRARY_DIRECTORY_NAME}/{to_group}/"
        for resource in resources:
            rewritten: list[str] = []
            changed = False
            for relative in getattr(resource, "library_paths", []) or []:
                text = str(relative or "").strip().replace("\\", "/").strip("/")
                if text.startswith(from_prefix):
                    rewritten.append(f"{to_prefix}{text[len(from_prefix):]}")
                    changed = True
                else:
                    rewritten.append(text)
            update: dict[str, Any] = {}
            if changed:
                update["library_paths"] = rewritten
            # Resources whose own file sits in the moved folder keep pointing at
            # the real bytes.
            for field_name in ("source", "canonical_source", "sandbox_path"):
                value = getattr(resource, field_name, None)
                raw = str(value or "").strip()
                if not raw or "://" in raw:
                    continue
                candidate = Path(raw).expanduser()
                if not self._is_within(candidate, library_root):
                    continue
                try:
                    relative = candidate.resolve(strict=False).relative_to(
                        (library_root.joinpath(*from_group.split("/"))).resolve(strict=False)
                    )
                except ValueError:
                    continue
                moved = library_root.joinpath(*to_group.split("/"), *relative.parts)
                update[field_name] = str(moved)
            if update:
                self._repository.save_resource(
                    workspace_id,
                    resource.model_copy(update=update),
                )


__all__ = [
    "LIBRARY_DIRECTORY_NAME",
    "LIBRARY_TRASH_DIRECTORY_NAME",
    "LibraryDownload",
    "LibraryError",
    "LibraryGroupsSnapshot",
    "LibraryService",
    "normalize_group_path",
    "normalize_library_relative_path",
]
