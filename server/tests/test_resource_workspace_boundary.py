import base64
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


@pytest.mark.parametrize("collection", [False, True])
def test_explicit_file_content_import_owns_bytes_without_external_path_authority(tmp_path, collection):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside_folder = tmp_path / "outside"
    outside_folder.mkdir()
    outside_file = outside_folder / "notes.md"
    outside_file.write_text("Original external file must stay untouched", encoding="utf-8")
    chosen_content = "# Python 元组\n元组固定元素引用；内部列表仍能修改。\n"
    service = _service(tmp_path)
    service.set_workspace_path_resolver(lambda _workspace_id: str(workspace_root))
    uploaded = service.upload("workspace-import", ResourceUploadRequest(
        workspace_id="workspace-import", kind="markdown", name="notes.md", source=str(outside_file),
        content=base64.b64encode(chosen_content.encode()).decode(), content_encoding="base64",
        **({"collection_path": "outside/notes.md", "collection_root": str(outside_folder)} if collection else {}),
    ))
    assert uploaded.source != str(outside_file)
    assert Path(uploaded.source).read_bytes() == chosen_content.encode()
    assert outside_file.read_text() == "Original external file must stay untouched"
    if collection:
        assert uploaded.collection_path == "outside/notes.md"
        assert uploaded.collection_root != str(outside_folder)
    indexed = service.index("workspace-import", ResourceIndexRequest(resource_id=uploaded.id))
    assert indexed.index_status == "indexed"


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
