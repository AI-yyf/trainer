from pathlib import Path

import pytest

from app.core.models import ResourceIndexRequest, ResourceUploadRequest
from app.db.repository import TrainerRepository
from app.ingest.service import IngestService
from app.memory.semantic import SemanticMemory
from app.resources.service import ResourceService


def _service(tmp_path: Path) -> ResourceService:
    return ResourceService(
        repository=TrainerRepository(tmp_path / "db.sqlite3"),
        ingest_service=IngestService(),
        semantic_memory=SemanticMemory(tmp_path / "semantic"),
    )


def test_index_rejects_persisted_local_file_outside_registered_workspace_root(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-index-file-boundary"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside root", encoding="utf-8")
    service = _service(tmp_path)

    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name=outside_file.name,
            source=str(outside_file),
        ),
    )
    service.set_workspace_path_resolver(lambda _workspace_id: str(workspace_root))

    with pytest.raises(PermissionError, match="active workspace root"):
        service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))


def test_index_rejects_persisted_local_folder_outside_registered_workspace_root(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-index-folder-boundary"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_folder = tmp_path / "outside-folder"
    outside_folder.mkdir()
    outside_file = outside_folder / "notes.md"
    outside_file.write_text("outside root", encoding="utf-8")
    service = _service(tmp_path)

    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name=outside_folder.name,
            source=str(outside_folder),
            source_type="folder",
            source_items=[str(outside_file)],
        ),
    )
    service.set_workspace_path_resolver(lambda _workspace_id: str(workspace_root))

    with pytest.raises(PermissionError, match="active workspace root"):
        service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))


def test_index_accepts_local_file_inside_registered_workspace_root(tmp_path: Path) -> None:
    workspace_id = "workspace-index-file-inside"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    source_file = workspace_root / "notes.md"
    source_file.write_text("Inside the registered workspace root.", encoding="utf-8")
    service = _service(tmp_path)

    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name=source_file.name,
            source=str(source_file),
        ),
    )
    service.set_workspace_path_resolver(lambda _workspace_id: str(workspace_root))

    indexed = service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))

    assert indexed.index_status == "indexed"


def test_index_accepts_managed_inline_file_with_registered_workspace_root(tmp_path: Path) -> None:
    workspace_id = "workspace-index-inline"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = _service(tmp_path)

    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name="inline.md",
            source="inline://inline.md",
            content="# Inline resource\nManaged by Trainer.",
        ),
    )
    service.set_workspace_path_resolver(lambda _workspace_id: str(workspace_root))

    indexed = service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))

    assert indexed.index_status == "indexed"


def test_index_leaves_remote_resource_unaffected_by_local_workspace_root(tmp_path: Path) -> None:
    workspace_id = "workspace-index-remote"
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    service = _service(tmp_path)
    remote_source = "vscode-remote://ssh-remote+devbox/home/dev/notes.md"

    uploaded = service.upload(
        workspace_id,
        ResourceUploadRequest(
            workspace_id=workspace_id,
            kind="markdown",
            name="notes.md",
            source=remote_source,
        ),
    )
    service.set_workspace_path_resolver(
        lambda _workspace_id: "vscode-remote://ssh-remote+devbox/home/dev"
    )

    indexed = service.index(workspace_id, ResourceIndexRequest(resource_id=uploaded.id))

    assert indexed.source == remote_source
    assert indexed.index_status == "failed"
