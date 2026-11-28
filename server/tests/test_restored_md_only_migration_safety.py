"""The Markdown-only migration never destroys the only copy of a resource.

The destructive pass writes the canonical Markdown first and only then removes
the legacy originals. A resource whose canonical Markdown is missing and whose
source is gone keeps its originals, and the result says so instead of
reporting a clean run.

Restored from server/tests/test_md_only_migration_safety.py at df0a3e2a^ (deleted in
df0a3e2a). The old file's fifth test,
``test_the_inline_upload_survives_without_a_readable_document``, is not part of this
restoration. Every old assertion is kept. Adapted:

* where the canonical Markdown is read (``markdown_path.is_file()``) and where the legacy
  originals are planted (``original_dir_for(...)``): the old tests used the workspace
  folder, which used to be the root the migration scans on a cold start. On a cold start
  that folder is the learner's code project, so the library root is now under the sidecar
  data root (``<data_dir>/canonical-resources/<workspace slug>``); with a bound learning
  folder it is ``<LibraryRoot>``. Both became ``carrier_root``, the tests run on both
  layouts, and each asserts the workspace folder gained no ``Trainer Library`` directory.
* ``test_the_deletion_chokepoint_refuses_without_a_readable_document`` keeps its old body: it
  already asked the service for its writable root. (The service is now reached through the
  typed ``_runtime(client)`` helper, which pyright accepts, instead of
  ``client.app.state.runtime``.)
* ``test_migration_never_deletes_originals_left_inside_the_workspace_folder`` keeps the
  part of the orphan test that still holds for a pre-change install: the migration does not
  scan the workspace folder any more, so legacy originals planted there are never deleted.
  It no longer reports them as unbacked; that is deliberately not asserted.
* ``_docx_bytes`` comes from canonical_doc_fixtures.py instead of the deleted
  test_canonical_markdown.py.
"""

from __future__ import annotations

from pathlib import Path

from canonical_doc_fixtures import _docx_bytes
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.resources.canonical_store import original_dir_for
from tests.test_restored_canonical_pipeline import (
    LAYOUTS,
    _runtime,
    carrier_root_for,
    data_dir_for,
)


def build_client(tmp_path: Path, *, bound: bool = False) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Markdown Migration Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir_for(tmp_path, bound=bound),
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


@LAYOUTS
def test_migration_keeps_the_only_copy_when_no_canonical_markdown_exists(
    tmp_path: Path,
    bound: bool,
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
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
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
        markdown_path = carrier_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()
        markdown_path.unlink()
        docx_path.unlink()

        originals = original_dir_for(carrier_root, resource_id)
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

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


@LAYOUTS
def test_migration_removes_originals_only_behind_a_readable_canonical_markdown(
    tmp_path: Path,
    bound: bool,
) -> None:
    """With a readable canonical Markdown, the originals are a leftover copy."""
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-clean"
    docx_path = workspace_root / "docs" / "kept.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Kept Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])
        markdown_path = carrier_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()

        originals = original_dir_for(carrier_root, resource_id)
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

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


@LAYOUTS
def test_migration_keeps_originals_behind_an_empty_canonical_markdown(
    tmp_path: Path,
    bound: bool,
) -> None:
    """An empty canonical document replaces nothing, so the originals stay."""
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-empty-markdown"
    docx_path = workspace_root / "docs" / "empty.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=bound)

    with build_client(tmp_path, bound=bound) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Empty Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])
        markdown_path = carrier_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()
        markdown_path.write_text("", encoding="utf-8")
        docx_path.unlink()

        originals = original_dir_for(carrier_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        only_copy = originals / "empty.docx"
        only_copy.write_bytes(_docx_bytes())

        preview = migrate(client, workspace_id, dry_run=True, confirm=False)
        assert preview["originals_to_delete"] == 0
        assert preview["originals_kept"] == 1

        result = migrate(client, workspace_id, dry_run=False, confirm=True)
        assert only_copy.is_file(), "the migration deleted the only copy of the resource"
        assert result.get("status") != "complete", result

        # The workspace folder is the learner's code project: no library was created in it.
        assert not (workspace_root / "Trainer Library").exists()


def test_migration_never_deletes_originals_left_inside_the_workspace_folder(
    tmp_path: Path,
) -> None:
    """The part of the old orphan test that still holds where it planted the originals.

    Before the change, a cold start kept the library under the workspace folder, so a
    pre-change install can have legacy originals inside the learner's code project. The
    migration no longer scans that folder: it must leave those originals alone. (It no
    longer reports them either; that part of the old test does not hold there and is
    asserted only for the Trainer-owned root, in the tests above.)
    """
    workspace_root = tmp_path / "workspace"
    workspace_id = "workspace-migration-legacy-location"
    docx_path = workspace_root / "docs" / "legacy.docx"
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    docx_path.write_bytes(_docx_bytes())
    carrier_root = carrier_root_for(tmp_path, workspace_id, bound=False)

    with build_client(tmp_path) as client:
        start_session(client, workspace_root, workspace_id)
        indexed = upload_and_index(
            client,
            workspace_id=workspace_id,
            name="Legacy Notes",
            source=docx_path,
        )
        resource_id = str(indexed["id"])

        markdown_path = carrier_root / str(indexed["canonical_markdown_path"])
        assert markdown_path.is_file()
        markdown_path.unlink()
        docx_path.unlink()

        originals = original_dir_for(workspace_root, resource_id)
        originals.mkdir(parents=True, exist_ok=True)
        only_copy = originals / "legacy.docx"
        only_copy.write_bytes(_docx_bytes())

        # The preview never promises to delete a copy it cannot replace.
        preview = migrate(client, workspace_id, dry_run=True, confirm=False)
        assert preview["status"] == "preview"
        assert preview["originals_to_delete"] == 0

        migrate(client, workspace_id, dry_run=False, confirm=True)

        # The only copy survives: the migration never deletes from the code project.
        assert only_copy.is_file(), "the migration deleted the only copy of the resource"


def test_the_deletion_chokepoint_refuses_without_a_readable_document(tmp_path: Path) -> None:
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
        service = _runtime(client).resource_service
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
