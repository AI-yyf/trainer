"""Trainer Library folder lane — downloads, targets and real-folder groups.

The capture fetch boundary is mocked the same way the browser-capture suite
mocks it; git and the archive transport are mocked per test. Everything below
them is real: workspace authority, trust gate, permission ladder, the actual
filesystem folders and the library resource bookkeeping.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.resources.library import (
    LIBRARY_DIRECTORY_NAME,
    LIBRARY_TRASH_DIRECTORY_NAME,
    LibraryService,
)
from app.resources.library_copy import (
    LIBRARY_COPY,
    SUPPORTED_LIBRARY_LANGUAGES,
    library_message,
)
from app.workspace.authority import PermissionLevel, WorkspaceAuthority
from tests.test_browser_capture import (
    _readonly_response,
    _start_session,
    minimal_pdf,
)

PROJECT_WORKSPACE = "workspace-library"


def build_client(tmp_path: Path, *, enable_network: bool = True) -> TestClient:
    settings = AppSettings(
        app_name="Trainer library folders",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-library-folders.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=enable_network,
    )
    return TestClient(create_app(settings))


def provision_workspace(
    client: TestClient,
    tmp_path: Path,
    *,
    trusted: bool = True,
    remote_name: str = "",
    workspace_id: str = PROJECT_WORKSPACE,
) -> tuple[str, Path, Path]:
    """Adopt a real project folder and pin its host trust attestation."""

    runtime = client.app.state.runtime
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    trainer_root = tmp_path / "trainer-root"
    trainer_root.mkdir(exist_ok=True)
    provisioning = runtime.provision_project_adoption(
        workspace_id=workspace_id,
        root_path=str(trainer_root),
        project_path=str(project),
        project_name="library-project",
    )
    context_id = provisioning.context_id
    runtime.memory_service.update_workspace_state(
        context_id,
        workspace_trusted=trusted,
        remote_name=remote_name,
        is_remote_workspace=bool(remote_name),
    )
    runtime.workspace_authority(context_id)
    return context_id, project, trainer_root


def assert_no_temp_leftovers(project: Path) -> None:
    assert not [item for item in project.rglob(".trainer-archive-*")], "archive staging left behind"
    assert not [item for item in project.rglob(".*.tmp*")], "atomic-write staging left behind"


# ------------------------------------------------------------------ PDF download


def test_pdf_download_saves_the_original_bytes_and_creates_the_target_dir(
    tmp_path, monkeypatch
) -> None:
    pdf_url = "https://files.example.com/papers/session-rotation.pdf"
    pdf_body = minimal_pdf(["Trainer library download marker 9182."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "title": "Session rotation",
                "download": True,
                "target_dir": "Trainer Library/Papers/Deep",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["saved_path"] == "Trainer Library/Papers/Deep/Session rotation.pdf"
        saved = project / "Trainer Library" / "Papers" / "Deep" / "Session rotation.pdf"
        # The original bytes — not the markdown snapshot — landed in the folder.
        assert saved.is_file()
        assert saved.read_bytes() == pdf_body
        # The library resource still owns its snapshot and records the folder.
        assert payload["library_paths"] == ["Trainer Library/Papers/Deep/Session rotation.pdf"]
        assert Path(payload["source"]).read_bytes() == pdf_body
        assert_no_temp_leftovers(project)


def test_pdf_download_into_the_default_folder_reuses_identical_bytes(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/default-folder.pdf"
    pdf_body = minimal_pdf(["Trainer default folder marker."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        first = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "title": "Default folder",
                "download": True,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["saved_path"] == "Trainer Library/Default folder.pdf"

        # A second capture of the same URL dedupes and re-downloads from the
        # owned snapshot: identical bytes are reused, never rewritten.
        second = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
            },
        )

        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["deduped"] is True
        assert payload["saved_path"] == "Trainer Library/Default folder.pdf"
        assert any(item.startswith("download:warning_existing_reused") for item in payload["warnings"])
        assert (project / "Trainer Library" / "Default folder.pdf").read_bytes() == pdf_body


def test_pdf_download_keeps_a_user_edited_file_and_saves_beside_it(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/edited.pdf"
    pdf_body = minimal_pdf(["Trainer collision marker."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        target = project / LIBRARY_DIRECTORY_NAME / "Edited.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4 user edited copy that must survive\n")

        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "title": "Edited",
                "download": True,
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        saved_name = Path(payload["saved_path"]).name
        assert saved_name != "Edited.pdf"
        assert saved_name.startswith("Edited-") and saved_name.endswith(".pdf")
        assert target.read_bytes().startswith(b"%PDF-1.4 user edited copy")
        assert (project / LIBRARY_DIRECTORY_NAME / saved_name).read_bytes() == pdf_body
        assert any(item.startswith("download:warning_collision_renamed") for item in payload["warnings"])


# --------------------------------------------------------------- GitHub download


def _repo_zip(entries: dict[str, str], top: str = "session-tools-main") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries.items():
            archive.writestr(f"{top}/{name}", text)
    return buffer.getvalue()


def test_github_download_prefers_git_clone(tmp_path, monkeypatch) -> None:
    repo_url = "https://github.com/example-org/session-tools"
    readme = "# Session Tools\n\nRotate signing keys before the deploy window.\n"
    readme_payload = json.dumps(
        {
            "name": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(readme.encode("utf-8")).decode("ascii"),
        }
    ).encode("utf-8")
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(readme_payload, url, "application/json"),
    )
    import app.resources.library_downloads as downloads

    monkeypatch.setattr(downloads.shutil, "which", lambda name: "/usr/bin/git")
    clone_calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        clone_calls.append(list(command))
        destination = Path(command[-1])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "README.md").write_text(readme, encoding="utf-8")
        (destination / ".git").mkdir(exist_ok=True)
        return downloads.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(downloads.subprocess, "run", fake_run)

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": repo_url,
                "kind": "github_repo",
                "download": True,
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["saved_path"] == "Trainer Library/session-tools"
        assert len(clone_calls) == 1
        assert clone_calls[0][1:3] == ["clone", "--depth"]
        assert clone_calls[0][-2] == "https://github.com/example-org/session-tools.git"
        assert (project / LIBRARY_DIRECTORY_NAME / "session-tools" / "README.md").is_file()
        assert not any(item.startswith("download:warning_") for item in payload["warnings"])


def test_github_download_falls_back_to_the_zip_archive_without_git(tmp_path, monkeypatch) -> None:
    repo_url = "https://github.com/example-org/session-tools"
    readme = "# Session Tools\n\nArchive fallback marker 5510.\n"
    readme_payload = json.dumps(
        {
            "name": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(readme.encode("utf-8")).decode("ascii"),
        }
    ).encode("utf-8")
    archive = _repo_zip({"README.md": readme, "src/app.py": "print('hi')\n"})
    archive_urls: list[str] = []

    def fake_fetch(url: str, **kwargs):
        if url.endswith("/readme"):
            return _readonly_response(readme_payload, url, "application/json")
        if url == "https://api.github.com/repos/example-org/session-tools":
            return _readonly_response(b'{"default_branch": "main"}', url, "application/json")
        archive_urls.append(url)
        return _readonly_response(archive, url, "application/zip")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)
    import app.resources.library_downloads as downloads

    monkeypatch.setattr(downloads, "fetch_url", fake_fetch)
    monkeypatch.setattr(downloads.shutil, "which", lambda name: None)

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": repo_url,
                "kind": "github_repo",
                "download": True,
                "target_dir": "Trainer Library/repos",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["saved_path"] == "Trainer Library/repos/session-tools"
        assert archive_urls == [
            "https://codeload.github.com/example-org/session-tools/zip/refs/heads/main"
        ]
        repo_dir = project / LIBRARY_DIRECTORY_NAME / "repos" / "session-tools"
        # The archive's single top-level folder is stripped: the repo contents
        # land directly in the target folder.
        assert (repo_dir / "README.md").read_text(encoding="utf-8") == readme
        assert (repo_dir / "src" / "app.py").is_file()
        assert any(item.startswith("download:warning_git_unavailable") for item in payload["warnings"])
        assert_no_temp_leftovers(project)


def test_github_download_refuses_a_traversal_archive_without_polluting_the_workspace(
    tmp_path, monkeypatch
) -> None:
    repo_url = "https://github.com/example-org/evil-repo"
    readme_payload = json.dumps(
        {
            "name": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(b"# Evil\n").decode("ascii"),
        }
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("evil-repo-main/README.md", "# Evil\n")
        archive.writestr("evil-repo-main/../../escape.txt", "escaped\n")
    hostile_archive = buffer.getvalue()

    def fake_fetch(url: str, **kwargs):
        if url.endswith("/readme"):
            return _readonly_response(readme_payload, url, "application/json")
        if url == "https://api.github.com/repos/example-org/evil-repo":
            return _readonly_response(b'{"default_branch": "main"}', url, "application/json")
        return _readonly_response(hostile_archive, url, "application/zip")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)
    import app.resources.library_downloads as downloads

    monkeypatch.setattr(downloads, "fetch_url", fake_fetch)
    monkeypatch.setattr(downloads.shutil, "which", lambda name: None)

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": repo_url,
                "kind": "github_repo",
                "download": True,
            },
        )

        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "download_failed"
        assert not (project / "Trainer Library" / "evil-repo").exists()
        assert not (tmp_path / "escape.txt").exists()
        assert not (project / "escape.txt").exists()


def test_download_failure_reports_honestly_and_registers_nothing(tmp_path, monkeypatch) -> None:
    repo_url = "https://github.com/example-org/unreachable"
    readme_payload = json.dumps(
        {
            "name": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(b"# Unreachable\n").decode("ascii"),
        }
    ).encode("utf-8")

    def fake_fetch(url: str, **kwargs):
        if url.endswith("/readme"):
            return _readonly_response(readme_payload, url, "application/json")
        from app.network_fetch import ControlledFetchError

        raise ControlledFetchError("http_status", f"HTTP 500 for {url}")

    monkeypatch.setattr("app.resources.capture.fetch_url", fake_fetch)
    import app.resources.library_downloads as downloads

    monkeypatch.setattr(downloads, "fetch_url", fake_fetch)
    monkeypatch.setattr(downloads.shutil, "which", lambda name: None)

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": repo_url,
                "kind": "github_repo",
                "download": True,
            },
        )
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "download_failed"
        assert not (project / LIBRARY_DIRECTORY_NAME).joinpath("unreachable").exists()
        # The capture itself was not registered: a failed download fails the
        # request instead of quietly landing half-done.
        library = client.get(
            "/memory/summary",
            params={"workspace_id": workspace_id},
        ).json()
        assert [
            item for item in library["memory"]["resources"] if "unreachable" in item["source"]
        ] == []


def test_github_download_is_refused_while_network_fetch_is_disabled(tmp_path, monkeypatch) -> None:
    repo_url = "https://github.com/example-org/offline-repo"
    readme_payload = json.dumps(
        {
            "name": "README.md",
            "encoding": "base64",
            "content": base64.b64encode(b"# Offline\n").decode("ascii"),
        }
    ).encode("utf-8")
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(readme_payload, url, "application/json"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        captured = client.post(
            "/resources/capture",
            json={"workspace_id": workspace_id, "url": repo_url, "kind": "github_repo"},
        )
        assert captured.status_code == 200, captured.text

        # A plain repository capture still fails honestly on the capture fetch,
        # while a deduped capture that only needs the download is refused with
        # the download-specific message — and creates nothing.
        client.app.state.runtime.resource_service.enable_network_fetch = False
        response = client.post(
            "/resources/capture",
            json={"workspace_id": workspace_id, "url": repo_url, "kind": "github_repo", "download": True},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "download_network_disabled"
        assert not (project / LIBRARY_DIRECTORY_NAME).exists()


# ------------------------------------------------------------ target governance


def test_download_refuses_a_target_outside_the_workspace_root(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/boundary.pdf"
    pdf_body = minimal_pdf(["Boundary marker."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (project / "link-out").symlink_to(outside, target_is_directory=True)

        traversal = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
                "target_dir": "../escape",
            },
        )
        assert traversal.status_code == 422, traversal.text
        assert traversal.json()["detail"]["code"] == "invalid_target_dir"

        absolute = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
                "target_dir": str(outside),
            },
        )
        assert absolute.status_code == 422, absolute.text
        assert absolute.json()["detail"]["code"] == "invalid_target_dir"

        # A symlink inside the workspace pointing outside it is caught by the
        # workspace authority boundary check, not by string matching.
        symlinked = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
                "target_dir": "link-out/Papers",
            },
        )
        assert symlinked.status_code == 422, symlinked.text
        assert symlinked.json()["detail"]["code"] == "target_outside_workspace"
        assert list(outside.iterdir()) == []


def test_download_requires_a_trusted_local_workspace(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/trust.pdf"
    pdf_body = minimal_pdf(["Trust marker."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        untrusted_id, project, _ = provision_workspace(client, tmp_path, trusted=False)
        untrusted = client.post(
            "/resources/capture",
            json={
                "workspace_id": untrusted_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
            },
        )
        assert untrusted.status_code == 403, untrusted.text
        assert untrusted.json()["detail"]["code"] == "library_not_writable"
        assert not (project / LIBRARY_DIRECTORY_NAME).exists()

        remote_id, _, _ = provision_workspace(
            client,
            tmp_path,
            remote_name="ssh-remote",
            workspace_id="workspace-library-remote",
        )
        remote = client.post(
            "/resources/capture",
            json={
                "workspace_id": remote_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
            },
        )
        assert remote.status_code == 403, remote.text
        assert remote.json()["detail"]["code"] == "library_not_writable"

        # No local project root at all: refused honestly instead of guessing.
        session_id = _start_session(client, "workspace-library-rootless")
        rootless = client.post(
            "/resources/capture",
            json={
                "session_id": session_id,
                "workspace_id": "workspace-library-rootless",
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
            },
        )
        assert rootless.status_code == 409, rootless.text
        assert rootless.json()["detail"]["code"] == "library_root_unavailable"


def test_download_refusal_message_follows_the_workspace_language(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/lang.pdf"
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(minimal_pdf(["Lang marker."]), url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, _, _ = provision_workspace(client, tmp_path, trusted=False)
        client.app.state.runtime.memory_service.update_workspace_state(
            workspace_id,
            response_language="ja-JP",
        )
        response = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "download": True,
            },
        )
        assert response.status_code == 403, response.text
        message = response.json()["detail"]["message"]
        assert "ライブラリ" in message


def test_download_rejects_kinds_that_cannot_be_downloaded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(b"<html>body</html>", url, "text/html"),
    )
    with build_client(tmp_path) as client:
        workspace_id, _, _ = provision_workspace(client, tmp_path)
        web = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": "https://blog.example.com/page",
                "kind": "web",
                "download": True,
            },
        )
        assert web.status_code == 422, web.text
        assert web.json()["detail"]["code"] == "download_kind_unsupported"

        # target_dir without download is a caller mistake, not a silent no-op.
        orphan_target = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": "https://blog.example.com/page",
                "kind": "web",
                "target_dir": "Trainer Library/Papers",
            },
        )
        assert orphan_target.status_code == 422, orphan_target.text


# ------------------------------------------------------------- library groups


def test_group_crud_creates_lists_renames_and_trashes_real_folders(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(
            minimal_pdf(["Group marker."]), url, "application/pdf"
        ),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        library_root = project / LIBRARY_DIRECTORY_NAME

        created = client.post("/library/groups", json={"workspace_id": workspace_id, "path": "Papers"})
        assert created.status_code == 200, created.text
        assert created.json()["created"] is True
        assert (library_root / "Papers").is_dir()

        again = client.post("/library/groups", json={"workspace_id": workspace_id, "path": "Papers"})
        assert again.status_code == 200, again.text
        assert again.json()["created"] is False

        nested = client.post(
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "Trainer Library/Papers/2026"},
        )
        assert nested.status_code == 200, nested.text
        assert (library_root / "Papers" / "2026").is_dir()

        tree = client.get("/library/groups", params={"workspace_id": workspace_id})
        assert tree.status_code == 200, tree.text
        payload = tree.json()
        assert payload["managed_root"] == LIBRARY_DIRECTORY_NAME
        assert payload["exists"] is True
        assert payload["trash_root"] == f"{LIBRARY_DIRECTORY_NAME}/{LIBRARY_TRASH_DIRECTORY_NAME}"
        names = [node["path"] for node in payload["groups"]]
        assert names == ["Papers"]
        assert [child["path"] for child in payload["groups"][0]["children"]] == ["Papers/2026"]

        # ``path``/``new_path`` is the workbench folder editor's spelling.
        renamed = client.post(
            "/library/groups/rename",
            json={"workspace_id": workspace_id, "path": "Papers", "new_path": "Reading"},
        )
        assert renamed.status_code == 200, renamed.text
        assert (library_root / "Reading" / "2026").is_dir()
        assert not (library_root / "Papers").exists()

        into_itself = client.post(
            "/library/groups/rename",
            json={"workspace_id": workspace_id, "from": "Reading", "to": "Reading/2027"},
        )
        assert into_itself.status_code == 422, into_itself.text
        assert into_itself.json()["detail"]["code"] == "group_rename_into_itself"

        root_delete = client.request(
            "DELETE",
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "Trainer Library"},
        )
        assert root_delete.status_code == 409, root_delete.text
        assert root_delete.json()["detail"]["code"] == "group_is_library_root"

        missing = client.request(
            "DELETE",
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "Missing"},
        )
        assert missing.status_code == 404, missing.text

        trashed = client.request(
            "DELETE",
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "Reading/2026"},
        )
        assert trashed.status_code == 200, trashed.text
        payload = trashed.json()
        assert payload["trashed"] is True
        assert payload["recoverable"] is True
        assert not (library_root / "Reading" / "2026").exists()
        trash_path = Path(payload["trash_path"])
        assert trash_path.parts[0:2] == (LIBRARY_DIRECTORY_NAME, LIBRARY_TRASH_DIRECTORY_NAME)
        assert (project / trash_path).is_dir()

        after = client.get("/library/groups", params={"workspace_id": workspace_id}).json()
        assert [node["path"] for node in after["groups"]] == ["Reading"]
        assert after["groups"][0]["children"] == []

        invalid = client.post(
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "../escape"},
        )
        assert invalid.status_code == 422, invalid.text
        assert invalid.json()["detail"]["code"] == "group_invalid_path"

        recreated = client.post("/library/groups", json={"workspace_id": workspace_id, "path": "Papers"})
        assert recreated.status_code == 200, recreated.text
        rename_conflict = client.post(
            "/library/groups/rename",
            json={"workspace_id": workspace_id, "from": "Reading", "to": "Papers"},
        )
        assert rename_conflict.status_code == 409, rename_conflict.text
        assert rename_conflict.json()["detail"]["code"] == "group_already_exists"


def test_group_resource_counts_follow_downloads_renames_and_trash(tmp_path, monkeypatch) -> None:
    pdf_url = "https://files.example.com/papers/counted.pdf"
    pdf_body = minimal_pdf(["Counted marker."])
    monkeypatch.setattr(
        "app.resources.capture.fetch_url",
        lambda url, **kwargs: _readonly_response(pdf_body, url, "application/pdf"),
    )

    with build_client(tmp_path) as client:
        workspace_id, project, _ = provision_workspace(client, tmp_path)
        captured = client.post(
            "/resources/capture",
            json={
                "workspace_id": workspace_id,
                "url": pdf_url,
                "kind": "pdf",
                "title": "Counted paper",
                "download": True,
                "target_dir": "Trainer Library/Papers",
            },
        )
        assert captured.status_code == 200, captured.text

        counted = client.get("/library/groups", params={"workspace_id": workspace_id}).json()
        assert counted["total_resource_count"] == 1
        papers = next(node for node in counted["groups"] if node["path"] == "Papers")
        assert papers["resource_count"] == 1
        assert papers["workspace_path"] == f"{LIBRARY_DIRECTORY_NAME}/Papers"

        client.post(
            "/library/groups/rename",
            json={"workspace_id": workspace_id, "from": "Papers", "to": "Reading"},
        )
        renamed = client.get("/library/groups", params={"workspace_id": workspace_id}).json()
        reading = next(node for node in renamed["groups"] if node["path"] == "Reading")
        assert reading["resource_count"] == 1
        assert renamed["total_resource_count"] == 1

        # The resource record follows the folder, not just the folder tree.
        resource = client.app.state.runtime.repository.list_resources(workspace_id)[0]
        assert resource.library_paths == [f"{LIBRARY_DIRECTORY_NAME}/Reading/Counted paper.pdf"]

        trashed = client.request(
            "DELETE",
            "/library/groups",
            json={"workspace_id": workspace_id, "path": "Reading"},
        )
        assert trashed.status_code == 200, trashed.text
        assert trashed.json()["moved_resource_count"] == 1
        after = client.get("/library/groups", params={"workspace_id": workspace_id}).json()
        assert after["groups"] == []
        # Trashed folders are not library groups, so they stop counting.
        assert after["total_resource_count"] == 0
        reloaded = client.app.state.runtime.repository.list_resources(workspace_id)[0]
        assert reloaded.library_paths[0].startswith(
            f"{LIBRARY_DIRECTORY_NAME}/{LIBRARY_TRASH_DIRECTORY_NAME}/"
        )

        # The recoverable bytes are still on disk under the recycle bin.
        trashed_file = project / trashed.json()["trash_path"] / "Counted paper.pdf"
        assert len(Path(trashed.json()["trash_path"]).parts) >= 3
        assert trashed_file.is_file()


def test_groups_require_a_trusted_local_workspace(tmp_path) -> None:
    with build_client(tmp_path) as client:
        untrusted_id, project, _ = provision_workspace(client, tmp_path, trusted=False)
        created = client.post(
            "/library/groups",
            json={"workspace_id": untrusted_id, "path": "Papers"},
        )
        assert created.status_code == 403, created.text
        assert created.json()["detail"]["code"] == "library_not_writable"
        assert not (project / LIBRARY_DIRECTORY_NAME).exists()

        listed = client.get("/library/groups", params={"workspace_id": untrusted_id})
        assert listed.status_code == 200, listed.text
        assert listed.json()["exists"] is False
        assert listed.json()["groups"] == []


# ------------------------------------------------------------------ unit pins


def test_library_copy_covers_all_eight_languages() -> None:
    expected = {"zh-CN", "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "ko-KR", "pt-BR"}
    assert set(SUPPORTED_LIBRARY_LANGUAGES) == expected
    assert set(LIBRARY_COPY) == {
        "library_root_unavailable",
        "library_not_writable",
        "invalid_target_dir",
        "target_outside_workspace",
        "download_network_disabled",
        "download_kind_unsupported",
        "download_source_missing",
        "download_failed",
        "library_write_denied",
        "group_missing_path",
        "group_invalid_path",
        "group_not_found",
        "group_already_exists",
        "group_is_library_root",
        "group_rename_into_itself",
        "group_mutation_failed",
        "warning_existing_reused",
        "warning_collision_renamed",
        "warning_git_unavailable",
        "warning_clone_fallback",
    }
    for code, templates in LIBRARY_COPY.items():
        assert set(templates) == expected, code
        for language, text in templates.items():
            assert text.strip(), (code, language)
            assert "\ufffd" not in text, (code, language)
            assert "\ue000" not in text and "\uf8ff" not in text, (code, language)
    # Every non-English copy differs from the English fallback.
    for code, templates in LIBRARY_COPY.items():
        english = templates["en-US"]
        for language in expected - {"en-US"}:
            assert templates[language] != english, (code, language)
    assert library_message("group_not_found", "pt-BR", path="Papers").endswith("Papers")
    assert library_message("library_root_unavailable", "de-DE")
    assert library_message("library_not_writable", "unknown-tag") == LIBRARY_COPY[
        "library_not_writable"
    ]["en-US"]


class _FakeRepository:
    def __init__(self) -> None:
        self.resources: dict[str, object] = {}

    def list_resources(self, workspace_id: str):
        return list(self.resources.values())

    def save_resource(self, workspace_id: str, resource) -> None:
        self.resources[resource.id] = resource


def test_artifact_names_keep_unicode_titles_and_strip_path_separators() -> None:
    from app.resources.library_downloads import safe_artifact_name

    assert safe_artifact_name("论文 摘要.pdf", fallback="paper", suffix=".pdf") == "论文 摘要.pdf"
    assert safe_artifact_name("../../etc/passwd", fallback="paper", suffix=".pdf") == "etc-passwd.pdf"
    assert safe_artifact_name("", fallback="captured-paper", suffix=".pdf") == "captured-paper.pdf"
    assert safe_artifact_name("a:b*c?d", fallback="paper", suffix=".pdf") == "a-b-c-d.pdf"


def test_library_permission_ladder_uses_the_existing_operation_levels(tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    authority = WorkspaceAuthority(root_path=str(workspace_root), initial_permission=PermissionLevel.INSPECT)
    authority.set_workspace_context(workspace_trusted=True)
    repository = _FakeRepository()
    service = LibraryService(repository, workspace_authority_resolver=lambda _ws: authority)

    pdf_body = minimal_pdf(["Ladder marker."])
    download = service.save_download(
        "workspace-ladder",
        kind="pdf",
        url="https://files.example.com/papers/ladder.pdf",
        title="Ladder",
        target_dir="Trainer Library/Papers",
        network_enabled=True,
        content_base64=base64.b64encode(pdf_body).decode("ascii"),
    )
    assert download.relative_path == f"{LIBRARY_DIRECTORY_NAME}/Papers/Ladder.pdf"
    assert (workspace_root / download.relative_path).read_bytes() == pdf_body

    # A repeat download of identical bytes touches an existing artifact path.
    repeated = service.save_download(
        "workspace-ladder",
        kind="pdf",
        url="https://files.example.com/papers/ladder.pdf",
        title="Ladder",
        target_dir="Trainer Library/Papers",
        network_enabled=True,
        content_base64=base64.b64encode(pdf_body).decode("ascii"),
    )
    assert repeated.created is False

    service.create_group("workspace-ladder", "Notes")
    service.rename_group("workspace-ladder", "Notes", "Archive")
    service.trash_group("workspace-ladder", "Archive")

    ledger = service.authority_ledger("workspace-ladder")
    operations = [record.operation for record in ledger]
    assert [operation for operation in operations if operation == "generate"]
    assert [operation for operation in operations if operation == "write"]
    assert [operation for operation in operations if operation == "mkdir"]
    assert [operation for operation in operations if operation == "rename"]
    assert [operation for operation in operations if operation == "delete"]
    for record in ledger:
        assert record.result == "allowed"
    levels = {record.operation: record.permission_level for record in ledger}
    assert levels["generate"] >= PermissionLevel.GENERATE
    assert levels["write"] >= PermissionLevel.APPLY
    assert levels["mkdir"] >= PermissionLevel.REORGANIZE
    assert levels["delete"] >= PermissionLevel.DESTRUCTIVE
