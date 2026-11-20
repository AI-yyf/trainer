"""The Markdown-only migration never destroys the only copy of a resource.

The destructive pass writes the canonical Markdown first and only then removes
the legacy originals. A resource whose canonical Markdown is missing and whose
source is gone keeps its originals, and the result says so instead of
reporting a clean run.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.resources.canonical_store import original_dir_for
from tests.test_canonical_markdown import _docx_bytes


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Markdown Migration Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-migration.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def start_session(client: TestClient, workspace_root: Path, workspace_id: str) -> str:
    workspace_root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/session/start",
        json={
            "workspace_id": workspace_id,
            "workspace_name": workspace_id,
            "workspace_path": str(workspace_root),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def upload_and_index(
    client: TestClient,
    *,
    workspace_id: str,
    name: str,
    source: Path,
) -> dict:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "docx",
            "name": name,
            "source": str(source),
        },
    )
    assert upload.status_code == 200, upload.text
    resource_id = upload.json()["id"]
    indexed = client.post(
        "/resource/index",
        json={
            "workspace_id": workspace_id,
            "resource_id": resource_id,
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def migrate(client: TestClient, workspace_id: str, *, dry_run: bool, confirm: bool) -> dict:
    response = client.post(
        "/resource/md-only/migrate",
        json={
            "workspace_id": workspace_id,
            "dry_run": dry_run,
            "confirm": confirm,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_migration_keeps_the_only_copy_when_no_canonical_markdown_exists(
    tmp_path: Path,
) -> None:
    """The legacy originals are the last copy: the migration must keep them.

    Reproduces the destructive path where the canonical Markdown was removed
    and the original source is gone, so the originals directory holds the only
    remaining bytes of the learner's document.
    """
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-orphan"
    docx_path = workspace_root / "docs" / "orphan.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Orphan Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])

        # The canonical Markdown disappears and the source is gone: only the
        # legacy originals copy is left.
        markdown_path = workspace_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()
        markdown_path.unlink()
        docx_path.unlink()

        originals = original_dir_for(workspace_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        only_copy = originals / "orphan.docx"
        only_copy.write_bytes(_docx_bytes())

        # The preview never promises to delete a copy it cannot replace.
        preview = migrate(client, workspace_id, dry_run=True, confirm=False)
        assert preview["status"] == "preview"
        assert preview["originals_to_delete"] == 0

        result = migrate(client, workspace_id, dry_run=False, confirm=True)

        # The only copy survives.
        assert only_copy.is_file(), "the migration deleted the only copy of the resource"
        assert any(
            failure["resource_id"] == resource_id for failure in result.get("failures", [])
        ), result
        assert result.get("status") != "complete", result


def test_migration_removes_originals_only_behind_a_readable_canonical_markdown(
    tmp_path: Path,
) -> None:
    """With a readable canonical Markdown, the originals are a leftover copy."""
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-clean"
    docx_path = workspace_root / "docs" / "kept.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Kept Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])
        markdown_path = workspace_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()

        originals = original_dir_for(workspace_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        leftover = originals / "kept.docx"
        leftover.write_bytes(_docx_bytes())

        preview = migrate(client, workspace_id, dry_run=True, confirm=False)
        assert preview["status"] == "preview"
        assert preview["originals_to_delete"] == 1

        result = migrate(client, workspace_id, dry_run=False, confirm=True)

        # The canonical Markdown is the artifact that remains.
        assert markdown_path.is_file()
        assert not leftover.exists()
        assert result.get("status") == "complete", result


def test_migration_keeps_originals_behind_an_empty_canonical_markdown(
    tmp_path: Path,
) -> None:
    """An empty canonical document replaces nothing, so the originals stay."""
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-empty-markdown"
    docx_path = workspace_root / "docs" / "empty.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Empty Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])
        markdown_path = workspace_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()
        markdown_path.write_text("", encoding="utf-8")
        docx_path.unlink()

        originals = original_dir_for(workspace_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        only_copy = originals / "empty.docx"
        only_copy.write_bytes(_docx_bytes())

        preview = migrate(client, workspace_id, dry_run=True, confirm=False)
        assert preview["originals_to_delete"] == 0
        assert preview["originals_kept"] == 1

        result = migrate(client, workspace_id, dry_run=False, confirm=True)
        assert only_copy.is_file(), "the migration deleted the only copy of the resource"
        assert result.get("status") != "complete", result


def test_the_deletion_chokepoint_refuses_without_a_readable_document(
    tmp_path: Path,
) -> None:
    """The one place the library drops an original is guarded itself.

    The guard does not depend on the caller: it re-checks the canonical
    document before it removes anything.
    """
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-chokepoint"
    docx_path = workspace_root / "docs" / "guarded.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Guarded Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])
        service = client.app.state.runtime.resource_service
        resource = next(
            candidate
            for candidate in service.repository.list_resources(workspace_id)
            if candidate.id == resource_id
        )

        writable_root = service._canonical_writable_root(workspace_id)
        assert writable_root is not None
        originals = original_dir_for(writable_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        guarded = originals / "guarded.docx"
        guarded.write_bytes(_docx_bytes())

        # A missing canonical document: the originals are the only copy.
        missing = resource.model_copy(
            update={"canonical_markdown_path": "Trainer Library/.trainer-resources/markdown/gone.md"}
        )
        removed, reason = service._remove_originals_behind_markdown(writable_root, missing)
        assert removed is False
        assert "kept" in reason
        assert guarded.is_file()

        # An empty canonical document replaces nothing either.
        empty_markdown = writable_root / "empty.md"
        empty_markdown.write_text("", encoding="utf-8")
        empty = resource.model_copy(update={"canonical_markdown_path": str(empty_markdown)})
        removed, reason = service._remove_originals_behind_markdown(writable_root, empty)
        assert removed is False
        assert guarded.is_file()

        # A readable canonical document stands behind the originals.
        readable_markdown = writable_root / "readable.md"
        readable_markdown.write_text("# Notes\n\nThe learner's own words.\n", encoding="utf-8")
        readable = resource.model_copy(update={"canonical_markdown_path": str(readable_markdown)})
        removed, reason = service._remove_originals_behind_markdown(writable_root, readable)
        assert removed is True, reason
        assert not guarded.exists()


def test_the_inline_upload_survives_without_a_readable_document(tmp_path: Path) -> None:
    """The last copy of an upload is only dropped behind a readable document."""
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-inline-guard"

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "text",
                "name": "coach-table.csv",
                "source": "inline://coach-table.csv",
                "content": "name,value\ncoach,1\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = str(uploaded.json()["id"])
        inline_source = Path(str(uploaded.json()["source"])).resolve(strict=False)
        assert inline_source.is_file()

        service = client.app.state.runtime.resource_service
        resource = next(
            candidate
            for candidate in service.repository.list_resources(workspace_id)
            if candidate.id == resource_id
        )

        # No canonical document yet: the upload is the only copy.
        service._discard_managed_inline_source(workspace_id, resource)
        assert inline_source.is_file()

        # A readable document stands behind it, so the upload is a leftover.
        markdown_path = workspace_root / "Trainer Library/.trainer-resources/markdown/kept.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# Coach table\n\nname,value\n", encoding="utf-8")
        readable = resource.model_copy(update={"canonical_markdown_path": str(markdown_path)})
        service._discard_managed_inline_source(workspace_id, readable)
        assert not inline_source.exists()
