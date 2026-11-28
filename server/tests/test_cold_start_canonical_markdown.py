"""A cold-start import still gets its canonical Markdown, under Trainer's data root.

The product contract lets a learner start before choosing a learning folder and promises
the code project stays untouched (§4); it also says canonical Markdown is the only library
artifact (§11). For a while both were "met" by writing the canonical copy into the
workspace folder, which on a cold start is the learner's code project. Removing that
fallback without a replacement dropped the artifact for cold-start imports: plain-text
search hits, no anchors, and the binary itself synced into the sandbox. The copy now goes
under the sidecar data root, next to the inline uploads and the search index of the same
workspace, and moves with them when a learning folder is bound later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from canonical_doc_fixtures import _docx_bytes

from app.core.config import Settings
from app.main import create_app
from app.resources.canonical import read_front_matter
from app.resources.canonical_store import managed_workspace_root

CANONICAL_PREFIX = "Trainer Library/.trainer-resources/markdown/"


def _files_under(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _layout(tmp_path: Path, *, bound: bool) -> tuple[Any, Any, Path, Path]:
    """A code project registered as the workspace, plus the sidecar data root the host would pass."""
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "main.py").write_text("print('learner code')\n", encoding="utf-8")
    (project_root / ".git").mkdir()
    (project_root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    if bound:
        data_dir = tmp_path / "Library Root" / ".trainer" / "runtime"   # a learning folder is bound
    else:
        data_dir = tmp_path / "globalStorage" / "sidecar"               # cold start
    app = create_app(Settings(data_dir=data_dir))
    return app, app.state.runtime, project_root, data_dir


async def _import(
    app: Any, workspace_id: str, project_root: Path, source: Path, *, kind: str, name: str
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as client:
        started = await client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Cold start",
                "workspace_path": str(project_root),
            },
        )
        assert started.status_code == 200, started.text
        # Exactly what the extension host posts for a file picked anywhere on disk:
        # the bytes travel inline, so the sidecar needs no access to that location.
        import base64

        uploaded = await client.post(
            "/resource/upload",
            json={
                "session_id": started.json()["session_id"],
                "workspace_id": workspace_id,
                "kind": kind,
                "name": name,
                "source": str(source),
                "content": base64.b64encode(source.read_bytes()).decode("ascii"),
                "content_encoding": "base64",
                "tags": [],
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        indexed = await client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert indexed.status_code == 200, indexed.text
        return dict(indexed.json(), _session_id=started.json()["session_id"])


async def _search(app: Any, workspace_id: str, session_id: str, query: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as client:
        response = await client.post(
            "/resource/search",
            json={"workspace_id": workspace_id, "session_id": session_id, "query": query, "top_k": 5},
        )
        assert response.status_code == 200, response.text
        return dict(response.json())


async def test_cold_start_docx_import_keeps_its_canonical_markdown_outside_the_code_project(
    tmp_path: Path,
) -> None:
    app, runtime, project_root, data_dir = _layout(tmp_path, bound=False)
    workspace_id = "ws-cold-docx"
    # The learner picks a file from wherever it lives; it is not inside the code project.
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    docx_path = downloads / "distributed-systems.docx"
    docx_path.write_bytes(_docx_bytes())
    project_before = _files_under(project_root)
    service = runtime.resource_service

    indexed = await _import(
        app, workspace_id, project_root, docx_path, kind="docx", name="Distributed Systems Notes"
    )

    relative = str(indexed["canonical_markdown_path"])
    assert relative.startswith(CANONICAL_PREFIX), indexed
    # The copy lives under Trainer's data root, never in the code project.
    markdown_path = service._canonical_markdown_path(
        workspace_id, runtime.repository.get_resource(workspace_id, str(indexed["id"]))
    )
    assert markdown_path is not None and markdown_path.is_file(), (relative, markdown_path)
    assert managed_workspace_root(data_dir, workspace_id) in markdown_path.parents
    assert project_root.resolve() not in markdown_path.resolve().parents
    markdown = markdown_path.read_text(encoding="utf-8")
    front = read_front_matter(markdown)
    assert front["resource_id"] == indexed["id"]
    assert front["source_type"] == "docx"
    assert "## Replication" in markdown
    assert "| Quorum | Meaning |" in markdown
    assert indexed["kind"] == "markdown"
    assert _files_under(project_root) == project_before

    # The sandbox gets the Markdown (and only Markdown), not the binary.
    sandbox_path = Path(str(indexed["sandbox_path"]))
    assert sandbox_path.suffix == ".md" and sandbox_path.is_file(), indexed
    assert data_dir.resolve() in sandbox_path.resolve().parents
    assert project_root.resolve() not in sandbox_path.resolve().parents

    # Search and the coach context read the Markdown body, with its headings.
    search = await _search(app, workspace_id, str(indexed["_session_id"]), "quorum reads intersect")
    hit = search["hits"][0]
    assert hit["resource_id"] == indexed["id"]
    assert hit["location"]["markdown_path"] == relative
    assert hit["location"].get("heading") == "Quorum"
    context = service.build_requested_resource_context(workspace_id, [indexed["id"]])
    fragments = context.get("resource_fragments") or []
    assert fragments, context
    assert "Quorum" in fragments[0]["snippet"] or "quorum" in fragments[0]["snippet"]
    assert fragments[0]["location"]["markdown_path"] == relative
    app.state.runtime.resource_service.close()


async def test_bound_learning_folder_keeps_the_canonical_copy_under_that_folder(tmp_path: Path) -> None:
    app, runtime, project_root, library_root = _layout(tmp_path, bound=True)
    workspace_id = "ws-bound-docx"
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    docx_path = downloads / "distributed-systems.docx"
    docx_path.write_bytes(_docx_bytes())
    project_before = _files_under(project_root)
    service = runtime.resource_service

    indexed = await _import(
        app, workspace_id, project_root, docx_path, kind="docx", name="Distributed Systems Notes"
    )

    record = runtime.repository.get_resource(workspace_id, str(indexed["id"]))
    markdown_path = service._canonical_markdown_path(workspace_id, record)
    assert markdown_path is not None and markdown_path.is_file()
    assert (library_root.parent.parent / "Trainer Library").resolve() in markdown_path.resolve().parents
    assert _files_under(project_root) == project_before
    app.state.runtime.resource_service.close()


async def test_a_canonical_copy_written_into_the_project_before_this_change_still_resolves(
    tmp_path: Path,
) -> None:
    """Existing installs have records whose copy sits in the workspace folder. Read-only lookup
    must keep finding them; nothing new is ever written there."""
    app, runtime, project_root, _data_dir = _layout(tmp_path, bound=False)
    workspace_id = "ws-legacy-docx"
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    docx_path = downloads / "distributed-systems.docx"
    docx_path.write_bytes(_docx_bytes())
    service = runtime.resource_service

    indexed = await _import(
        app, workspace_id, project_root, docx_path, kind="docx", name="Distributed Systems Notes"
    )
    record = runtime.repository.get_resource(workspace_id, str(indexed["id"]))
    current = service._canonical_markdown_path(workspace_id, record)
    assert current is not None and current.is_file()
    relative = str(record.canonical_markdown_path)

    # Turn the record into what a pre-change cold start would have produced.
    legacy = project_root / relative
    legacy.parent.mkdir(parents=True)
    current.unlink()
    legacy.write_bytes(b"# legacy copy inside the project\n")

    assert service._canonical_markdown_path(workspace_id, record) == legacy
    app.state.runtime.resource_service.close()


@pytest.mark.parametrize("bound", [False, True])
async def test_the_canonical_root_is_trainer_owned_and_never_the_code_project(
    tmp_path: Path, bound: bool
) -> None:
    app, runtime, project_root, data_dir = _layout(tmp_path, bound=bound)
    service = runtime.resource_service

    root = service._canonical_writable_root("ws-any")

    assert root is not None
    if bound:
        # A bound learning folder owns the library; the data root sits inside it.
        assert root.resolve() == (data_dir.parent.parent).resolve()
    else:
        # Cold start: Trainer's data root owns the copy until a folder is bound.
        assert root.resolve() == managed_workspace_root(data_dir, "ws-any").resolve()
        assert data_dir.resolve() in root.resolve().parents
    assert root.resolve() != project_root.resolve()
    assert project_root.resolve() not in root.resolve().parents
    app.state.runtime.resource_service.close()
