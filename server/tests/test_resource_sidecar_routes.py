from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

from app.core.models import derive_resource_trust_state
from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Resource Route Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-resource-routes.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def upload_and_index_markdown(client: TestClient, *, workspace_id: str, text: str) -> dict[str, object]:
    upload = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": "coach-notes.md",
            "source": "inline://coach-notes.md",
            "content": text,
            "content_encoding": "utf-8",
            "tags": ["coach", "resource-route"],
        },
    )
    assert upload.status_code == 200
    uploaded = upload.json()

    indexed = client.post(
        "/resource/index",
        json={
            "workspace_id": workspace_id,
            "resource_id": uploaded["id"],
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200
    return indexed.json()


def test_resource_trust_state_matches_training_contract() -> None:
    assert derive_resource_trust_state(0.75, "fresh", []) == "trusted"
    assert derive_resource_trust_state(0.75, "fresh", ["  "]) == "trusted"
    assert derive_resource_trust_state(0.95, "fresh", ["thin_content"]) == "unknown"
    assert derive_resource_trust_state(0.95, "stale", []) == "stale"
    assert derive_resource_trust_state(0.95, "fresh", ["blocked_source"]) == "untrusted"


def test_resource_routes_project_trust_state_into_index_and_memory_snapshots(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-trust-projection"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Trust projection\nThis indexed resource has enough verified content for training.\n",
        )
        summary = client.get("/memory/summary", params={"workspace_id": workspace_id})

    assert indexed["index_status"] == "indexed"
    assert indexed["freshness"] == "fresh"
    assert indexed["trust_score"] >= 0.75
    assert indexed["trust_state"] == "trusted"
    assert summary.status_code == 200, summary.text
    resources = summary.json()["memory"]["resources"]
    assert len(resources) == 1
    assert resources[0]["id"] == indexed["id"]
    assert resources[0]["trust_state"] == "trusted"


def test_resource_search_route_returns_indexed_hits(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-search"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Coach notes\nPreview me inside the trainer search route.\n",
        )

        response = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "coach notes preview",
                "top_k": 5,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == workspace_id
    assert payload["total"] >= 1
    assert payload["ranking_strategy"] == "lexical_first"
    assert payload["filters"]["project_scope"] == workspace_id
    top_hit = payload["hits"][0]
    assert top_hit["resource_id"] == indexed["id"]
    assert top_hit["title"] == "coach-notes.md"
    assert top_hit["citation_id"] == f"citation:{indexed['id']}"
    assert top_hit["project_scope"] == workspace_id
    assert top_hit["preview_kind"] in {"markdown", "text"}
    assert top_hit["rank_reasons"]


@pytest.mark.parametrize("rerank_field", ["semantic_rerank", "provider_rerank"])
def test_resource_search_rejects_unavailable_reranking(tmp_path: Path, rerank_field: str) -> None:
    workspace_id = "workspace-resource-rerank-capability"
    with build_client(tmp_path) as client:
        compatible = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "coach",
                "semantic_rerank": False,
                "provider_rerank": False,
            },
        )
        rejected = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "coach",
                rerank_field: True,
            },
        )

    assert compatible.status_code == 200
    assert rejected.status_code == 422
    assert rerank_field in rejected.text


def test_resource_upload_persists_safe_collection_path_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    workspace_id = "workspace-collection-contract"
    source_root = tmp_path / "source"
    source = source_root / "nested" / "alpha" / "readme.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Collection path\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                "collection_path": "source/nested/alpha/readme.md",
                "collection_root": str(source_root),
            },
        )
        assert uploaded.status_code == 200
        uploaded_payload = uploaded.json()
        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": uploaded_payload["id"],
                "enable_network": False,
            },
        )
        assert indexed.status_code == 200
        rejected = [
            client.post(
                "/resource/upload",
                json={
                    "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                    "collection_path": collection_path,
                },
            )
            for collection_path in ("nested/../escape.md", "/absolute/readme.md", r"nested\\readme.md")
        ]
        path_only = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                "collection_path": "source/nested/alpha/readme.md",
            },
        )
        root_only = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                "collection_root": str(source_root),
            },
        )

        stored = client.app.state.runtime.repository.get_resource(workspace_id, uploaded_payload["id"])

    assert uploaded_payload["collection_path"] == "source/nested/alpha/readme.md"
    assert uploaded_payload["collection_root"] == str(source_root.resolve())
    assert indexed.json()["collection_path"] == "source/nested/alpha/readme.md"
    assert indexed.json()["collection_root"] == str(source_root.resolve())
    assert stored is not None
    assert stored.collection_path == "source/nested/alpha/readme.md"
    assert stored.collection_root == str(source_root.resolve())
    assert [response.status_code for response in rejected] == [400, 400, 400]
    assert all("collection_path" in response.json()["detail"] for response in rejected)
    assert path_only.status_code == 400
    assert root_only.status_code == 400
    assert "collection_path and collection_root" in path_only.json()["detail"]
    assert "collection_path and collection_root" in root_only.json()["detail"]


def test_resource_upload_rejects_outside_active_workspace_without_leaking_paths(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-boundary-route"
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    outside_source = tmp_path.parent / "outside-resource.md"
    outside_source.write_text("outside", encoding="utf-8")

    with build_client(tmp_path) as client:
        client.app.state.runtime.resource_service.set_workspace_path_resolver(
            lambda _workspace_id: str(workspace_root),
        )
        response = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "outside-resource.md",
                "source": str(outside_source),
            },
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Resource source is outside an authorized workspace or collection.",
    }
    assert str(outside_source) not in response.text


def test_resource_upload_rejects_forged_or_mismatched_collection_roots(tmp_path: Path) -> None:
    workspace_id = "workspace-collection-root-validation"
    source_root = tmp_path / "source-root"
    source = source_root / "nested" / "alpha" / "readme.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Collection root\n", encoding="utf-8")
    forged_root = tmp_path / "forged-root"
    forged_root.mkdir()

    with build_client(tmp_path) as client:
        forged = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                "collection_path": "forged-root/nested/alpha/readme.md",
                "collection_root": str(forged_root),
            },
        )
        mismatched = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "readme.md",
                "source": str(source),
                "collection_path": "source-root/nested/beta/readme.md",
                "collection_root": str(source_root),
            },
        )

    assert forged.status_code == 400
    assert "collection_root" in forged.json()["detail"]
    assert mismatched.status_code == 400
    assert "collection_path" in mismatched.json()["detail"]


def test_resource_upload_and_index_uses_verified_collection_roots(tmp_path: Path) -> None:
    workspace_id = "workspace-collection-root-sandbox"
    first_root = tmp_path / "first-root"
    second_root = tmp_path / "second-root"
    first_alpha = first_root / "nested" / "alpha" / "readme.md"
    first_beta = first_root / "nested" / "beta" / "readme.md"
    second_alpha = second_root / "nested" / "alpha" / "readme.md"
    for source, content in (
        (first_alpha, "first alpha"),
        (first_beta, "first beta"),
        (second_alpha, "second alpha"),
    ):
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")

    def upload_and_index(source: Path, root: Path) -> dict[str, object]:
        collection_path = "/".join((root.name, *source.relative_to(root).parts))
        upload = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": source.name,
                "source": str(source),
                "collection_path": collection_path,
                "collection_root": str(root),
            },
        )
        assert upload.status_code == 200
        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": upload.json()["id"],
                "enable_network": False,
            },
        )
        assert indexed.status_code == 200
        return indexed.json()

    with build_client(tmp_path) as client:
        indexed_first_alpha = upload_and_index(first_alpha, first_root)
        indexed_first_beta = upload_and_index(first_beta, first_root)
        indexed_second_alpha = upload_and_index(second_alpha, second_root)

    first_alpha_path = Path(str(indexed_first_alpha["sandbox_path"]))
    first_beta_path = Path(str(indexed_first_beta["sandbox_path"]))
    second_alpha_path = Path(str(indexed_second_alpha["sandbox_path"]))
    assert first_alpha_path.parents[2] == first_beta_path.parents[2]
    assert first_alpha_path.parents[2] != second_alpha_path.parents[2]
    assert first_alpha_path.read_text(encoding="utf-8") == "first alpha"
    assert first_beta_path.read_text(encoding="utf-8") == "first beta"
    assert second_alpha_path.read_text(encoding="utf-8") == "second alpha"


def test_resource_delete_route_removes_search_hits_and_returns_audit_trail(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-delete"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Delete proof\nThis resource should disappear from search after delete.\n",
        )

        search_before = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "delete proof disappear",
                "top_k": 5,
            },
        )
        assert search_before.status_code == 200
        assert search_before.json()["total"] >= 1

        deleted = client.post(
            "/resource/delete",
            json={
                "workspace_id": workspace_id,
                "resource_id": indexed["id"],
            },
        )
        assert deleted.status_code == 200
        deleted_payload = deleted.json()

        search_after = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "delete proof disappear",
                "top_k": 5,
            },
        )

    assert deleted_payload["removed"] is True
    assert deleted_payload["checkpoint_id"]
    assert deleted_payload["ledger_entry_id"].startswith("evt-")
    assert deleted_payload["patch"]
    assert deleted_payload["diff_summary"]
    assert deleted_payload["primary_trashed_path"]
    assert deleted_payload["search_index_removed"] is True
    assert search_after.status_code == 200
    assert search_after.json()["total"] == 0


def test_sandbox_restore_route_restores_trashed_resource_path(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-restore"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Restore proof\nThis resource should come back from trash.\n",
        )

        deleted = client.post(
            "/resource/delete",
            json={
                "workspace_id": workspace_id,
                "resource_id": indexed["id"],
            },
        )
        assert deleted.status_code == 200
        trashed_path = deleted.json()["primary_trashed_path"]
        assert isinstance(trashed_path, str) and trashed_path

        restored = client.post(
            "/sandbox/restore",
            json={
                "workspace_id": workspace_id,
                "path": trashed_path,
            },
        )

    assert restored.status_code == 200
    payload = restored.json()
    assert "coach-notes" in payload["selected_path"]
    assert payload["selected_path"].endswith(".md")
    assert payload["authority"]["checkpoint_count"] >= 2


def test_resource_restore_route_rehydrates_record_and_requires_reindex(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-logical-restore"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Restore record\nThis resource must return as a governed library item.\n",
        )
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        assert client.app.state.runtime.repository.get_resource(workspace_id, indexed["id"]) is None

        restored = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert restored.status_code == 200, restored.text
        restored_payload = restored.json()
        restored_record = restored_payload["resource"]
        restored_from_repository = client.app.state.runtime.repository.get_resource(
            workspace_id,
            indexed["id"],
        )
        search_before_reindex = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "governed library item",
                "top_k": 5,
            },
        )
        reindexed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"], "enable_network": False},
        )
        search_after_reindex = client.post(
            "/resource/search",
            json={
                "workspace_id": workspace_id,
                "query": "governed library item",
                "top_k": 5,
            },
        )

    assert restored_payload["restored"] is True
    assert restored_payload["reindex_required"] is True
    assert restored_record["id"] == indexed["id"]
    assert restored_record["sandbox_path"] == indexed["sandbox_path"]
    assert restored_record["parse_status"] == "pending"
    assert restored_record["index_status"] == "pending"
    assert restored_from_repository is not None
    assert restored_from_repository.id == indexed["id"]
    assert restored_from_repository.index_status == "pending"
    assert search_before_reindex.status_code == 200
    assert search_before_reindex.json()["total"] == 0
    assert reindexed.status_code == 200, reindexed.text
    assert search_after_reindex.status_code == 200
    assert search_after_reindex.json()["total"] >= 1


def test_resource_trash_route_is_durable_workspace_scoped_and_minimal(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-trash"
    other_workspace_id = "workspace-resource-trash-other"
    source_root = tmp_path / "collection-root"
    source = source_root / "docs" / "delete-me.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Durable trash\n", encoding="utf-8")

    with build_client(tmp_path) as client:
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "delete-me.md",
                "source": str(source),
                "collection_path": "collection-root/docs/delete-me.md",
                "collection_root": str(source_root),
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": resource_id},
        )
        assert deleted.status_code == 200, deleted.text

        other = client.post(
            "/resource/upload",
            json={
                "workspace_id": other_workspace_id,
                "kind": "markdown",
                "name": "other-workspace.md",
                "source": "inline://other-workspace.md",
                "content": "# Other workspace\n",
            },
        )
        assert other.status_code == 200, other.text
        other_deleted = client.post(
            "/resource/delete",
            json={"workspace_id": other_workspace_id, "resource_id": other.json()["id"]},
        )
        assert other_deleted.status_code == 200, other_deleted.text

    # A new app creates a new ResourceService over the same durable repository.
    with build_client(tmp_path) as restarted_client:
        trash = restarted_client.get("/resource/trash", params={"workspace_id": workspace_id})
        other_trash = restarted_client.get(
            "/resource/trash",
            params={"workspace_id": other_workspace_id},
        )

        assert trash.status_code == 200, trash.text
        assert other_trash.status_code == 200, other_trash.text
        payload = trash.json()
        assert payload["workspace_id"] == workspace_id
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["resource_id"] == resource_id
        assert item["title"] == "delete-me.md"
        assert item["collection_path"] == "collection-root/docs/delete-me.md"
        assert item["deleted_at"] == deleted.json()["deleted_at"]
        assert item["recoverable"] is True
        assert set(item) == {"resource_id", "title", "collection_path", "deleted_at", "recoverable"}
        assert {"source", "collection_root", "sandbox_path", "deletion_payload", "tags"}.isdisjoint(item)
        assert [entry["resource_id"] for entry in other_trash.json()["items"]] == [
            other.json()["id"]
        ]

        restored = restarted_client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": resource_id},
        )
        empty_trash = restarted_client.get(
            "/resource/trash",
            params={"workspace_id": workspace_id},
        )

    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] is True
    assert empty_trash.status_code == 200, empty_trash.text
    assert empty_trash.json() == {"workspace_id": workspace_id, "items": []}


def test_resource_index_rehydrates_transient_registry_after_sidecar_restart(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-registry-rehydrate"
    with build_client(tmp_path) as first_client:
        uploaded = first_client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "restart-proof.md",
                "source": "inline://restart-proof.md",
                "content": "# Restart proof\nPersisted resources must index after a sidecar restart.\n",
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]

    with build_client(tmp_path) as restarted_client:
        indexed = restarted_client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )

    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["id"] == resource_id
    assert indexed.json()["index_status"] == "indexed"


def test_resource_restore_preserves_verified_collection_identity(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-collection-restore"
    source_root = tmp_path / "knowledge-root"
    source = source_root / "docs" / "nested.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Collection restore\nKeep the verified hierarchy.\n", encoding="utf-8")
    collection_path = f"{source_root.name}/docs/nested.md"

    with build_client(tmp_path) as client:
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": source.name,
                "source": str(source),
                "collection_path": collection_path,
                "collection_root": str(source_root),
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        indexed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert indexed.status_code == 200, indexed.text
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": resource_id},
        )
        assert deleted.status_code == 200, deleted.text
        restored = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": resource_id},
        )
        restored_resource = restored.json()["resource"]
        sandbox_state = restored.json()["sandbox_state"]
        restored_link_count = sandbox_state["linked_resource_count"]

    assert restored.status_code == 200, restored.text
    assert restored_resource["collection_path"] == collection_path
    assert restored_resource["collection_root"] == str(source_root.resolve())
    assert restored_link_count == 1


def test_sandbox_state_route_returns_authoritative_preview_and_selection(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-state"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# State proof\nRefresh should keep the current governed preview alive.\n",
        )
        sandbox_path = indexed["sandbox_path"]
        assert isinstance(sandbox_path, str) and sandbox_path

        response = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "selected_path": sandbox_path,
                "preview_path": sandbox_path,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == workspace_id
    assert payload["selected_path"] == sandbox_path
    assert payload["managed_roots"] == ["plan", "cards", "knowledge", "sources", "notes", "outputs"]
    assert payload["linked_resource_count"] >= 1
    assert payload["capability_summary"]["permission_state"] in {"coach_only", "level_destructive"}
    assert payload["preview"]["path"] == sandbox_path
    assert str(payload["preview"]["title"]).startswith("coach-notes")
    assert payload["preview"]["preview_kind"] in {"markdown", "text"}


def test_session_start_without_workspace_trusted_stays_untrusted_and_denies_sandbox_write(
    tmp_path: Path,
) -> None:
    """POST /session/start omit-trust path: authority fail-closed, not trusted theater."""
    workspace_id = "workspace-session-start-omit-trust"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Omit Trust Session",
                "workspace_path": str(project_root),
            },
        )
        assert started.status_code == 200, started.text

        state = client.get("/sandbox/state", params={"workspace_id": workspace_id})
        assert state.status_code == 200, state.text
        assert state.json()["capability_summary"]["platform"]["workspace_trust_state"] == "untrusted"
        assert state.json()["capability_summary"]["platform"]["workspace_trust_state"] != "trusted"

        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is False

        written = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "notes/omit-trust.md",
                "content": "library-local",
                "create": True,
            },
        )
        assert written.status_code == 200, written.text
        assert authority.is_workspace_trusted is False


def test_sandbox_state_route_applies_host_trust_to_capability_summary(tmp_path: Path) -> None:
    workspace_id = "workspace-host-trust-list-state"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Host Trust List State",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert started.status_code == 200, started.text

        unknown = client.get("/sandbox/state", params={"workspace_id": workspace_id})
        assert unknown.status_code == 200, unknown.text
        # Without host query params, memory from session/start already attested trusted.
        assert unknown.json()["capability_summary"]["platform"]["workspace_trust_state"] == "trusted"

        untrusted = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "workspace_trusted": "false",
                "remote_name": "",
            },
        )
        assert untrusted.status_code == 200, untrusted.text
        assert untrusted.json()["capability_summary"]["platform"]["workspace_trust_state"] == "untrusted"

        remote = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "workspace_trusted": "true",
                "remote_name": "ssh-remote",
            },
        )
        assert remote.status_code == 200, remote.text
        assert remote.json()["capability_summary"]["platform"]["workspace_trust_state"] == "remote"

        trusted = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "workspace_trusted": "true",
                "remote_name": "",
            },
        )
        assert trusted.status_code == 200, trusted.text
        assert trusted.json()["capability_summary"]["platform"]["workspace_trust_state"] == "trusted"


def test_sandbox_root_route_applies_host_trust_before_list_state(tmp_path: Path) -> None:
    workspace_id = "workspace-host-trust-sandbox-root"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"
    custom_root = (tmp_path / "projects" / "fixed-root").resolve(strict=False)

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Host Trust Sandbox Root",
                "workspace_path": str(project_root),
                "workspace_trusted": False,
                "remote_name": "",
            },
        )
        assert started.status_code == 200, started.text

        trusted = client.post(
            "/sandbox/root",
            json={
                "workspace_id": workspace_id,
                "root_path": str(custom_root),
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert trusted.status_code == 200, trusted.text
        assert trusted.json()["capability_summary"]["platform"]["workspace_trust_state"] == "trusted"

        remote = client.post(
            "/sandbox/root",
            json={
                "workspace_id": workspace_id,
                "clear": True,
                "workspace_trusted": True,
                "remote_name": "ssh-remote",
            },
        )
        assert remote.status_code == 200, remote.text
        assert remote.json()["capability_summary"]["platform"]["workspace_trust_state"] == "remote"

        untrusted = client.post(
            "/sandbox/root",
            json={
                "workspace_id": workspace_id,
                "clear": True,
                "workspace_trusted": False,
                "remote_name": "",
            },
        )
        assert untrusted.status_code == 200, untrusted.text
        assert untrusted.json()["capability_summary"]["platform"]["workspace_trust_state"] == "untrusted"


def test_sandbox_write_route_applies_host_untrusted_and_denies_write(tmp_path: Path) -> None:
    """Previously-missing mutation route must re-attest untrusted before write."""
    workspace_id = "workspace-host-trust-sandbox-write"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Host Trust Sandbox Write",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert started.status_code == 200, started.text

        allowed = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "notes/trusted.md",
                "content": "ok",
                "create": True,
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert allowed.status_code == 200, allowed.text

        blocked_project_trust = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "notes/untrusted-library.md",
                "content": "library-local",
                "create": True,
                "workspace_trusted": False,
                "remote_name": "",
            },
        )
        assert blocked_project_trust.status_code == 200, blocked_project_trust.text
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is False


def test_session_message_and_turn_reattest_host_trust_mid_session(tmp_path: Path) -> None:
    workspace_id = "workspace-mid-session-trust-flip"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Mid Session Trust",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert started.status_code == 200, started.text
        session_id = started.json()["session_id"]
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is True

        # Provider may fail; attestation must still run before coach work.
        client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "message": "trust flip probe",
                "workspace_trusted": False,
                "remote_name": "",
            },
        )
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is False

        client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "trust flip probe turn",
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is True


def test_workspace_authority_route_returns_sandbox_authority_summary(tmp_path: Path) -> None:
    workspace_id = "workspace-authority-refresh"
    with build_client(tmp_path) as client:
        response = client.get("/workspace/authority", params={"workspace_id": workspace_id})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["workspace_id"] == workspace_id
    assert payload["authority"]["authority_source"] == "workspace_authority_service"
    # No opened project: do not invent one by copying the sandbox root.
    assert payload["authority"]["active_workspace_root"] == ""
    assert payload["authority"]["root_uri"] == payload["authority"]["resource_write_evidence"]["target_root"]
    assert payload["authority"]["trash_root"]
    assert payload["authority"]["authority_scope"] == "trainer_sandbox"
    assert payload["authority"]["resource_write_allowed"] is True
    assert payload["authority"]["resource_write_evidence"] == {
        "operation": "write",
        "scope": "trainer_sandbox",
        "target_root": payload["authority"]["resource_write_evidence"]["target_root"],
        "allowed": True,
        "reason": "Trainer artifact writes are confined to the managed sandbox root.",
    }
    assert payload["authority_source"] == payload["authority"]["authority_source"]
    assert payload["authority"]["sandbox_authority"]["authority_scope"] == "trainer_sandbox"
    assert payload["authority"]["project_authority"] is None


def test_sandbox_preview_route_returns_file_preview(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-preview"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Preview proof\nRead this from the governed sandbox preview route.\n",
        )
        sandbox_path = indexed["sandbox_path"]
        assert isinstance(sandbox_path, str) and sandbox_path

        response = client.post(
            "/sandbox/preview",
            json={
                "workspace_id": workspace_id,
                "path": sandbox_path,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == sandbox_path
    assert str(payload["title"]).startswith("coach-notes")
    assert payload["preview_kind"] in {"markdown", "text"}
    assert "Preview proof" in payload["content"]


def test_sandbox_preview_route_maps_boundary_and_missing_paths_to_client_errors(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-resource-preview-errors"
    with build_client(tmp_path) as client:
        outside = client.post(
            "/sandbox/preview",
            json={"workspace_id": workspace_id, "path": "../../outside"},
        )
        missing = client.post(
            "/sandbox/preview",
            json={"workspace_id": workspace_id, "path": "does-not-exist.md"},
        )

    assert outside.status_code == 422
    assert outside.json()["detail"] == "Sandbox path must stay inside the active workspace root."
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Sandbox path was not found."


def _write_minimal_docx(path: Path, paragraphs: list[str]) -> None:
    """Tiny OpenXML zip — enough for suffix/kind emit without heavy deps."""
    import zipfile

    xml_paragraphs = "".join(
        f"<w:p><w:r><w:t>{paragraph.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{xml_paragraphs}</w:body>
</w:document>""",
        )


def test_sandbox_preview_docx_emits_document_kind_and_docx_path(tmp_path: Path) -> None:
    """Sidecar preview for .docx must emit document kind + original .docx path (host attaches assetUri)."""
    workspace_id = "workspace-docx-preview-emit"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Bootstrap sandbox\nPlace a sibling docx for emit-shape proof.\n",
        )
        sibling_md = Path(str(indexed["sandbox_path"]))
        docx_path = sibling_md.with_name("coach-notes.docx")
        _write_minimal_docx(docx_path, ["DOCX emit shape stays grounded."])

        response = client.post(
            "/sandbox/preview",
            json={
                "workspace_id": workspace_id,
                "path": str(docx_path),
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert str(payload["path"]).lower().endswith(".docx")
    assert Path(payload["path"]).name == "coach-notes.docx"
    assert payload["preview_kind"] == "document"
    # Honesty: sidecar snapshot has no webview assetUri — extension host must attach.
    assert payload.get("asset_uri") in (None, "")
    assert payload.get("assetUri") in (None, "")


def test_sandbox_preview_route_applies_host_trust_attestation(tmp_path: Path) -> None:
    """Preview must re-attest host trust; untrusted/remote must not stay trusted theater."""
    workspace_id = "workspace-host-trust-sandbox-preview"
    project_root = tmp_path / "opened-project"
    project_root.mkdir()
    data_root = tmp_path / "sidecar-data"

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Host Trust Sandbox Preview",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert started.status_code == 200, started.text

        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Preview trust proof\nHost attestation must land before preview.\n",
        )
        sandbox_path = indexed["sandbox_path"]
        assert isinstance(sandbox_path, str) and sandbox_path

        trusted = client.post(
            "/sandbox/preview",
            json={
                "workspace_id": workspace_id,
                "path": sandbox_path,
                "workspace_trusted": True,
                "remote_name": "",
            },
        )
        assert trusted.status_code == 200, trusted.text
        assert "Preview trust proof" in trusted.json()["content"]
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is True
        assert authority.is_remote_workspace is False

        untrusted = client.post(
            "/sandbox/preview",
            json={
                "workspace_id": workspace_id,
                "path": sandbox_path,
                "workspace_trusted": False,
                "remote_name": "",
            },
        )
        # Inspect preview may still return content; authority must not stay trusted.
        assert untrusted.status_code == 200, untrusted.text
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_workspace_trusted is False

        remote = client.post(
            "/sandbox/preview",
            json={
                "workspace_id": workspace_id,
                "path": sandbox_path,
                "workspace_trusted": True,
                "remote_name": "ssh-remote",
            },
        )
        assert remote.status_code == 200, remote.text
        authority = client.app.state.runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_remote_workspace is True
        # Remote must never paint as trusted-local theater.
        state = client.get("/sandbox/state", params={"workspace_id": workspace_id})
        assert state.status_code == 200, state.text
        assert state.json()["capability_summary"]["platform"]["workspace_trust_state"] == "remote"
        assert state.json()["capability_summary"]["platform"]["workspace_trust_state"] != "trusted"


def test_sandbox_mkdir_route_creates_nested_directories_inside_sandbox(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-mkdir"
    with build_client(tmp_path) as client:
        response = client.post(
            "/sandbox/mkdir",
            json={
                "workspace_id": workspace_id,
                "path": "packs/remote/ssh",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    expected_path = (tmp_path / "sandboxes" / workspace_id / "packs" / "remote" / "ssh").resolve(strict=False)
    created_path = Path(payload["selected_path"]).resolve(strict=False)
    assert created_path == expected_path
    assert expected_path.exists()
    assert payload["preview"]["path"] == str(expected_path)
    assert payload["preview"]["node_kind"] == "directory"
    assert payload["preview"]["metadata"]["child_count"] == 0
    assert payload["total_directories"] >= 18


def test_sandbox_write_route_creates_file_inside_sandbox(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-write"
    with build_client(tmp_path) as client:
        response = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "packs/remote/ssh/notes.md",
                "content": "# Sandbox write proof\nThis file came from the governed write route.\n",
                "create": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    expected_path = (tmp_path / "sandboxes" / workspace_id / "packs" / "remote" / "ssh" / "notes.md").resolve(
        strict=False
    )
    assert Path(payload["path"]).resolve(strict=False) == expected_path
    assert expected_path.exists()
    assert payload["relative_path"] == "packs/remote/ssh/notes.md"
    assert payload["preview_kind"] in {"markdown", "text"}
    assert "Sandbox write proof" in payload["content"]


def test_sandbox_rename_route_moves_file_inside_sandbox(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-rename"
    with build_client(tmp_path) as client:
        created = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "packs/remote/ssh/notes.md",
                "content": "rename proof\n",
                "create": True,
            },
        )
        assert created.status_code == 200
        original_path = Path(created.json()["path"]).resolve(strict=False)

        renamed = client.post(
            "/sandbox/rename",
            json={
                "workspace_id": workspace_id,
                "path": str(original_path),
                "new_path": "packs/debug/minimal-loop.md",
            },
        )

    assert renamed.status_code == 200
    payload = renamed.json()
    renamed_path = (tmp_path / "sandboxes" / workspace_id / "packs" / "debug" / "minimal-loop.md").resolve(
        strict=False
    )
    assert not original_path.exists()
    assert renamed_path.exists()
    assert Path(payload["path"]).resolve(strict=False) == renamed_path
    assert payload["relative_path"] == "packs/debug/minimal-loop.md"


def test_sandbox_delete_route_moves_path_into_trash(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-delete-path"
    with build_client(tmp_path) as client:
        created = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "packs/remote/ssh/notes.md",
                "content": "delete proof\n",
                "create": True,
            },
        )
        assert created.status_code == 200
        original_path = Path(created.json()["path"]).resolve(strict=False)

        deleted = client.post(
            "/sandbox/delete",
            json={
                "workspace_id": workspace_id,
                "path": str(original_path),
            },
        )

    assert deleted.status_code == 200
    payload = deleted.json()
    trash_root = Path(payload["trash_root_path"]).resolve(strict=False)
    assert not original_path.exists()
    assert trash_root.exists()
    assert any(candidate.name == "notes.md" for candidate in trash_root.rglob("notes.md"))
    assert payload["selected_path"] in {None, ""}
    assert payload["ready"] is True


def test_workspace_path_keeps_managed_artifacts_under_sidecar_data_root(tmp_path: Path) -> None:
    workspace_id = "workspace-carrier-root"
    data_root = tmp_path / "sidecar-data"
    workspace_root = tmp_path / "project-root"
    workspace_root.mkdir(parents=True, exist_ok=True)

    with build_client(data_root) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Carrier Root Proof",
                "workspace_path": str(workspace_root),
            },
        )
        assert started.status_code == 200

        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "text",
                "name": "coach-table.csv",
                "source": "inline://coach-table.csv",
                "content": "name,value\ncoach,1\n",
                "content_encoding": "utf-8",
                "tags": ["carrier-root", "csv"],
            },
        )
        assert uploaded.status_code == 200
        uploaded_payload = uploaded.json()
        uploaded_source = Path(uploaded_payload["source"]).resolve(strict=False)
        expected_inline_root = (data_root / "inline-resources" / workspace_id).resolve(strict=False)
        uploaded_source.relative_to(expected_inline_root)
        assert not (workspace_root / ".trainer" / "search" / "index.sqlite3").exists()

        indexed = client.post(
            "/resource/index",
            json={
                "workspace_id": workspace_id,
                "resource_id": uploaded_payload["id"],
                "enable_network": False,
            },
        )
        assert indexed.status_code == 200
        indexed_payload = indexed.json()
        sandbox_path = Path(indexed_payload["sandbox_path"]).resolve(strict=False)
        expected_sandbox_root = (data_root / "sandboxes" / workspace_id).resolve(strict=False)
        sandbox_path.relative_to(expected_sandbox_root)
        assert (data_root / "search-indexes" / workspace_id / "index.sqlite3").exists()
        assert not (workspace_root / ".trainer" / "search" / "index.sqlite3").exists()

        state = client.get(
            "/sandbox/state",
            params={
                "workspace_id": workspace_id,
                "selected_path": str(sandbox_path),
                "preview_path": str(sandbox_path),
            },
        )

    assert state.status_code == 200
    payload = state.json()
    preview_artifact_path = Path(
        payload["preview"]["metadata"]["preview_artifact_path"]
    ).resolve(strict=False)
    expected_preview_root = (data_root / "previews" / workspace_id).resolve(strict=False)
    preview_artifact_path.relative_to(expected_preview_root)
    assert payload["root_path"] == str(expected_sandbox_root)
    assert payload["sandbox_root_path"] == str(expected_sandbox_root)
    assert payload["managed_roots"] == ["plan", "cards", "knowledge", "sources", "notes", "outputs"]
    assert payload["workspace_root_path"] == str(workspace_root.resolve(strict=False))
    assert payload["active_workspace_root"] == str(workspace_root.resolve(strict=False))
    assert payload["authority"]["root_uri"] == str(expected_sandbox_root)
    assert payload["authority"]["active_workspace_root"] == str(workspace_root.resolve(strict=False))


def test_sandbox_root_route_sets_and_clears_fixed_workspace_root(tmp_path: Path) -> None:
    workspace_id = "workspace-fixed-sandbox-root"
    custom_root = (tmp_path / "projects" / "opened-folder").resolve(strict=False)

    with build_client(tmp_path) as client:
        set_response = client.post(
            "/sandbox/root",
            json={
                "workspace_id": workspace_id,
                "root_path": str(custom_root),
            },
        )
        assert set_response.status_code == 200
        set_payload = set_response.json()
        runtime = client.app.state.runtime
        assert set_payload["root_path"] == str(custom_root)
        assert set_payload["sandbox_root_path"] == str(custom_root)
        assert custom_root.exists()
        assert runtime.resolve_workspace_sandbox_root(workspace_id) == str(custom_root)
        workspace_state = runtime.memory_service.snapshot(workspace_id).workspace
        assert workspace_state["sandbox_root_override"] == str(custom_root)
        assert workspace_state["learning_project_prompt_status"] == "linked"

        clear_response = client.post(
            "/sandbox/root",
            json={
                "workspace_id": workspace_id,
                "clear": True,
            },
        )

    assert clear_response.status_code == 200
    clear_payload = clear_response.json()
    default_root = (tmp_path / "sandboxes" / workspace_id).resolve(strict=False)
    assert clear_payload["root_path"] == str(default_root)
    assert clear_payload["sandbox_root_path"] == str(default_root)
    assert runtime.resolve_workspace_sandbox_root(workspace_id) is None
    cleared_workspace_state = runtime.memory_service.snapshot(workspace_id).workspace
    assert cleared_workspace_state["sandbox_root_override"] == ""


def test_sandbox_root_route_rejects_workspace_root_and_ancestor_but_allows_sibling(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-sandbox-root-boundary"
    workspace_root = tmp_path / "opened-workspace"
    workspace_root.mkdir()
    ancestor_root = tmp_path
    nested_root = workspace_root / "nested-sandbox"
    nested_root.mkdir()
    sibling_root = tmp_path / "resource-sandbox"

    with build_client(tmp_path / "sidecar-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Sandbox boundary",
                "workspace_path": str(workspace_root),
            },
        )
        assert started.status_code == 200

        equal_root = client.post(
            "/sandbox/root",
            json={"workspace_id": workspace_id, "root_path": str(workspace_root)},
        )
        ancestor = client.post(
            "/sandbox/root",
            json={"workspace_id": workspace_id, "root_path": str(ancestor_root)},
        )
        nested = client.post(
            "/sandbox/root",
            json={"workspace_id": workspace_id, "root_path": str(nested_root)},
        )
        sibling = client.post(
            "/sandbox/root",
            json={"workspace_id": workspace_id, "root_path": str(sibling_root)},
        )

    assert equal_root.status_code == 422
    assert ancestor.status_code == 422
    assert nested.status_code == 422
    assert "active VS Code workspace root" in equal_root.json()["detail"]
    assert "active VS Code workspace root" in ancestor.json()["detail"]
    assert "live inside it" in nested.json()["detail"]
    assert sibling.status_code == 200
    assert sibling.json()["sandbox_root_path"] == str(sibling_root.resolve(strict=False))


def test_sandbox_root_route_does_not_persist_rejected_workspace_override(tmp_path: Path) -> None:
    workspace_id = "workspace-rejected-sandbox-root"
    workspace_root = tmp_path / "opened-workspace"
    workspace_root.mkdir()

    with build_client(tmp_path / "sidecar-data") as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Rejected sandbox root",
                "workspace_path": str(workspace_root),
            },
        )
        assert started.status_code == 200
        response = client.post(
            "/sandbox/root",
            json={"workspace_id": workspace_id, "root_path": str(workspace_root)},
        )
        runtime = client.app.state.runtime

    assert response.status_code == 422
    assert runtime.resolve_workspace_sandbox_root(workspace_id) is None
    assert runtime.memory_service.snapshot(workspace_id).workspace.get("sandbox_root_override", "") == ""


def test_resource_restore_compensates_second_artifact_failure_and_allows_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_id = "workspace-resource-atomic-restore"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Atomic restore\nBoth artifacts must return together.\n",
        )
        runtime = client.app.state.runtime
        resource = runtime.repository.get_resource(workspace_id, indexed["id"])
        assert resource is not None
        primary_path = Path(str(resource.sandbox_path))
        extracted_path = primary_path.parent / "extracted" / "outline.md"
        extracted_path.parent.mkdir()
        extracted_path.write_text("secondary artifact", encoding="utf-8")
        runtime.repository.save_resource(
            workspace_id,
            resource.model_copy(update={"extracted_artifact_path": str(extracted_path)}),
        )

        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        trashed_paths = deleted.json()["trashed_paths"]
        assert len(trashed_paths) == 2
        assert all(Path(path).exists() for path in trashed_paths.values())

        sandbox_service = runtime.sandbox_service
        assert sandbox_service is not None
        original_move = sandbox_service._move_path
        move_count = 0

        def fail_second_restore(source: Path, destination: Path) -> None:
            nonlocal move_count
            move_count += 1
            if move_count == 2:
                raise OSError("injected second artifact restore failure")
            original_move(source, destination)

        monkeypatch.setattr(sandbox_service, "_move_path", fail_second_restore)
        failed_restore = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        failed_trash = client.get("/resource/trash", params={"workspace_id": workspace_id})

        assert failed_restore.status_code == 409
        assert runtime.repository.get_resource(workspace_id, indexed["id"]) is None
        assert not primary_path.exists()
        assert not extracted_path.exists()
        assert all(Path(path).exists() for path in trashed_paths.values())
        assert failed_trash.status_code == 200, failed_trash.text
        assert failed_trash.json()["items"][0]["recoverable"] is True
        assert move_count >= 3

        monkeypatch.setattr(sandbox_service, "_move_path", original_move)
        retried_restore = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )

    assert retried_restore.status_code == 200, retried_restore.text
    assert retried_restore.json()["restored"] is True
    assert primary_path.exists()
    assert extracted_path.exists()
    assert all(not Path(path).exists() for path in trashed_paths.values())
    assert runtime.repository.get_resource(workspace_id, indexed["id"]) is not None


def test_resource_trash_marks_missing_artifacts_not_recoverable(tmp_path: Path) -> None:
    workspace_id = "workspace-resource-missing-trash-artifact"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Missing Trash artifact\nA missing archive must not be recoverable.\n",
        )
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        trashed_path = deleted.json()["primary_trashed_path"]
        assert isinstance(trashed_path, str) and trashed_path
        Path(trashed_path).unlink()

        trash = client.get("/resource/trash", params={"workspace_id": workspace_id})
        restored = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        runtime = client.app.state.runtime

    assert trash.status_code == 200, trash.text
    assert trash.json()["items"][0]["recoverable"] is False
    assert restored.status_code == 409
    assert runtime.repository.get_resource(workspace_id, indexed["id"]) is None


@pytest.mark.parametrize("activation_failure", ["false", "raises"])
def test_resource_restore_returns_artifacts_to_trash_when_activation_fails(
    tmp_path: Path,
    monkeypatch,
    activation_failure: str,
) -> None:
    workspace_id = f"workspace-resource-activation-{activation_failure}"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Activation compensation\nDurable activation controls completion.\n",
        )
        runtime = client.app.state.runtime
        resource = runtime.repository.get_resource(workspace_id, indexed["id"])
        assert resource is not None
        primary_path = Path(str(resource.sandbox_path))
        extracted_path = primary_path.parent / "extracted" / "activation.md"
        extracted_path.parent.mkdir()
        extracted_path.write_text("activation artifact", encoding="utf-8")
        runtime.repository.save_resource(
            workspace_id,
            resource.model_copy(update={"extracted_artifact_path": str(extracted_path)}),
        )

        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        trashed_paths = deleted.json()["trashed_paths"]
        original_activate = runtime.repository.restore_deleted_resource

        if activation_failure == "false":
            monkeypatch.setattr(
                runtime.repository,
                "restore_deleted_resource",
                lambda _workspace_id, _resource: False,
            )
        else:
            def raise_activation_failure(_workspace_id, _resource):
                raise RuntimeError("injected tombstone activation failure")

            monkeypatch.setattr(
                runtime.repository,
                "restore_deleted_resource",
                raise_activation_failure,
            )

        failed_restore = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )

        assert failed_restore.status_code == 409
        assert runtime.repository.get_resource(workspace_id, indexed["id"]) is None
        assert runtime.repository.get_deleted_resource(workspace_id, indexed["id"]) is not None
        assert not primary_path.exists()
        assert not extracted_path.exists()
        assert all(Path(path).exists() for path in trashed_paths.values())

        monkeypatch.setattr(runtime.repository, "restore_deleted_resource", original_activate)
        retried_restore = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )

    assert retried_restore.status_code == 200, retried_restore.text
    assert primary_path.exists()
    assert extracted_path.exists()
    assert all(not Path(path).exists() for path in trashed_paths.values())


def test_resource_restore_serializes_same_tombstone_across_requests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_id = "workspace-resource-restore-lock"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Restore lock\nOnly one restore may own a tombstone at a time.\n",
        )
        runtime = client.app.state.runtime
        resource = runtime.repository.get_resource(workspace_id, indexed["id"])
        assert resource is not None
        primary_path = Path(str(resource.sandbox_path))
        extracted_path = primary_path.parent / "extracted" / "lock.md"
        extracted_path.parent.mkdir()
        extracted_path.write_text("lock artifact", encoding="utf-8")
        runtime.repository.save_resource(
            workspace_id,
            resource.model_copy(update={"extracted_artifact_path": str(extracted_path)}),
        )
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        trashed_paths = deleted.json()["trashed_paths"]

        activation_started = Event()
        release_activation = Event()
        second_finished = Event()
        original_activate = runtime.repository.restore_deleted_resource
        activation_count = 0

        def block_first_activation(restore_workspace_id, restored_resource):
            nonlocal activation_count
            activation_count += 1
            if activation_count == 1:
                activation_started.set()
                assert release_activation.wait(timeout=5)
            return original_activate(restore_workspace_id, restored_resource)

        monkeypatch.setattr(runtime.repository, "restore_deleted_resource", block_first_activation)
        responses: dict[str, object] = {}

        def restore_in_thread(label: str, finished: Event | None = None) -> None:
            responses[label] = client.post(
                "/resource/restore",
                json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
            )
            if finished is not None:
                finished.set()

        first = Thread(target=restore_in_thread, args=("first",), daemon=True)
        second = Thread(target=restore_in_thread, args=("second", second_finished), daemon=True)
        first.start()
        assert activation_started.wait(timeout=5)
        second.start()
        assert not second_finished.wait(timeout=0.2)
        release_activation.set()
        first.join(timeout=5)
        second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    first_response = responses["first"]
    second_response = responses["second"]
    assert first_response.status_code == 200
    assert second_response.status_code == 404
    assert runtime.repository.get_resource(workspace_id, indexed["id"]) is not None
    assert primary_path.exists()
    assert extracted_path.exists()
    assert all(not Path(path).exists() for path in trashed_paths.values())


def test_resource_restore_keeps_committed_record_when_derived_refreshes_fail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_id = "workspace-resource-post-commit-refresh"
    with build_client(tmp_path) as client:
        indexed = upload_and_index_markdown(
            client,
            workspace_id=workspace_id,
            text="# Post commit refresh\nDerived state must not undo recovery.\n",
        )
        started = client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Post commit refresh"},
        )
        assert started.status_code == 200, started.text
        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        runtime = client.app.state.runtime
        sandbox_service = runtime.sandbox_service
        assert sandbox_service is not None

        def fail_sandbox_state(*_args, **_kwargs):
            raise RuntimeError("injected sandbox state refresh failure")

        def fail_session_refresh(_workspace_id):
            raise RuntimeError("injected session refresh failure")

        original_restore_artifacts = sandbox_service.restore_resource_artifacts

        def restore_then_break_derived_refreshes(*args, **kwargs):
            result = original_restore_artifacts(*args, **kwargs)
            monkeypatch.setattr(runtime.memory_service, "snapshot", fail_session_refresh)
            return result

        monkeypatch.setattr(sandbox_service, "list_state", fail_sandbox_state)
        monkeypatch.setattr(
            sandbox_service,
            "restore_resource_artifacts",
            restore_then_break_derived_refreshes,
        )
        restored = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": indexed["id"]},
        )
        trash = client.get("/resource/trash", params={"workspace_id": workspace_id})

    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"] is True
    assert restored.json()["sandbox_state"] is None
    assert runtime.repository.get_resource(workspace_id, indexed["id"]) is not None
    assert trash.status_code == 200, trash.text
    assert trash.json() == {"workspace_id": workspace_id, "items": []}
