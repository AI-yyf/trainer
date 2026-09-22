"""TR-059/TR-076: uploaded resources pin a SHA-256 content hash; when a
resource is deleted, evidence records citing that content version are flagged
with ``source_deleted`` so old citations degrade honestly instead of silently
pointing at nothing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.settings import AppSettings
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Evidence Source Deletion Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-evidence-source-deletion.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def upload_resource(client: TestClient, *, workspace_id: str, content: str) -> dict:
    uploaded = client.post(
        "/resource/upload",
        json={
            "workspace_id": workspace_id,
            "kind": "markdown",
            "name": "cited-source.md",
            "source": "inline://cited-source.md",
            "content": content,
            "content_encoding": "utf-8",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()


def find_evidence(runtime: TrainerRuntime, attempt_id: str, evidence_id: str) -> dict:
    store = runtime.attempt_store
    assert store is not None
    items = store.list_evidence(attempt_id)
    matches = [item for item in items if item.get("evidence_id") == evidence_id]
    assert matches, f"evidence {evidence_id} not found"
    return matches[0]


def start_attempt(client: TestClient, *, workspace_id: str, card_id: str) -> dict:
    started = client.post(
        "/training/attempt/start",
        json={"workspace_id": workspace_id, "card_id": card_id},
    )
    assert started.status_code == 200, started.text
    return started.json()["attempt"]


def test_upload_pins_sha256_content_hash(tmp_path: Path) -> None:
    workspace_id = "workspace-evidence-hash"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        content = "# Cited source\nStable content for hash pinning.\n"
        record = upload_resource(client, workspace_id=workspace_id, content=content)

        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert record["content_hash"] == expected
        store = runtime.resource_version_store
        assert store is not None
        assert store.current_content_hash(workspace_id, record["id"]) == expected


def test_reupload_of_same_content_bumps_version(tmp_path: Path) -> None:
    workspace_id = "workspace-evidence-reupload"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        store = runtime.resource_version_store
        assert store is not None
        content = "# Same content\n"
        first = upload_resource(client, workspace_id=workspace_id, content=content)
        second = upload_resource(client, workspace_id=workspace_id, content=content)

        assert first["id"] != second["id"]
        assert store.current_content_hash(workspace_id, first["id"]) == store.current_content_hash(
            workspace_id, second["id"]
        )


def test_resource_delete_flags_evidence_citing_deleted_content(tmp_path: Path) -> None:
    workspace_id = "workspace-evidence-delete"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        content = "# Delete me\nEvidence cites this content version.\n"
        record = upload_resource(client, workspace_id=workspace_id, content=content)
        content_hash = record["content_hash"]
        assert content_hash

        attempt = start_attempt(client, workspace_id=workspace_id, card_id="card-1")
        evidence_resp = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": content_hash,
                "result": "passed",
            },
        )
        assert evidence_resp.status_code == 200, evidence_resp.text
        evidence_id = evidence_resp.json()["evidence"]["evidence_id"]

        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": record["id"]},
        )
        assert deleted.status_code == 200, deleted.text

        evidence = find_evidence(runtime, attempt["attempt_id"], evidence_id)
        assert evidence["source_deleted"] is True
        assert "source deleted" in evidence["limitations"]


def test_resource_delete_leaves_unrelated_evidence_untouched(tmp_path: Path) -> None:
    workspace_id = "workspace-evidence-unrelated"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        record = upload_resource(
            client,
            workspace_id=workspace_id,
            content="# Unrelated delete\nDifferent content entirely.\n",
        )

        attempt = start_attempt(client, workspace_id=workspace_id, card_id="card-1")
        other_hash = hashlib.sha256(b"different artifact").hexdigest()
        evidence_resp = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": other_hash,
                "result": "passed",
            },
        )
        assert evidence_resp.status_code == 200, evidence_resp.text
        evidence_id = evidence_resp.json()["evidence"]["evidence_id"]

        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": record["id"]},
        )
        assert deleted.status_code == 200, deleted.text

        evidence = find_evidence(runtime, attempt["attempt_id"], evidence_id)
        assert evidence.get("source_deleted") is not True


def test_index_pins_hash_for_legacy_file_resource_without_version(tmp_path: Path) -> None:
    """A resource uploaded before versioning existed gets its content hash
    pinned at (re-)index time, enabling citation traceability retroactively."""
    workspace_id = "workspace-evidence-legacy-index"
    content = "# Legacy resource\nUploaded before content pinning existed.\n"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        store = runtime.resource_version_store
        assert store is not None
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "legacy.md",
                "source": "inline://legacy.md",
                "content": content,
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        # Simulate a pre-versioning row: wipe the pinned versions.
        store_conn = store._connect()
        try:
            store_conn.execute(
                "DELETE FROM resource_versions WHERE workspace_id = ? AND resource_id = ?",
                (workspace_id, resource_id),
            )
            store_conn.commit()
        finally:
            store_conn.close()

        indexed = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert indexed.status_code == 200, indexed.text
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert indexed.json()["content_hash"] == expected
        assert store.current_content_hash(workspace_id, resource_id) == expected


def test_reindex_appends_version_only_when_content_changed(tmp_path: Path) -> None:
    workspace_id = "workspace-evidence-reindex-version"
    content = "# Versioned resource\nOriginal content.\n"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        store = runtime.resource_version_store
        assert store is not None
        uploaded = client.post(
            "/resource/upload",
            json={
                "workspace_id": workspace_id,
                "kind": "markdown",
                "name": "versioned.md",
                "source": "inline://versioned.md",
                "content": content,
                "content_encoding": "utf-8",
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]

        # Re-index without any change: no new version row.
        first = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert first.status_code == 200, first.text
        connection = store._connect()
        try:
            count_after_first = connection.execute(
                "SELECT COUNT(*) AS n FROM resource_versions WHERE workspace_id = ? AND resource_id = ?",
                (workspace_id, resource_id),
            ).fetchone()["n"]
        finally:
            connection.close()
        assert count_after_first == 1

        # Content changes on disk; the re-index appends a second version.
        source_path = Path(first.json()["source"])
        source_path.write_bytes("# Versioned resource\nChanged content.\n".encode("utf-8"))
        second = client.post(
            "/resource/index",
            json={"workspace_id": workspace_id, "resource_id": resource_id, "enable_network": False},
        )
        assert second.status_code == 200, second.text
        connection = store._connect()
        try:
            rows = connection.execute(
                """SELECT content_hash, version FROM resource_versions
                   WHERE workspace_id = ? AND resource_id = ? ORDER BY version""",
                (workspace_id, resource_id),
            ).fetchall()
        finally:
            connection.close()
        assert [row["version"] for row in rows] == [1, 2]
        assert rows[0]["content_hash"] != rows[1]["content_hash"]
        assert second.json()["content_hash"] == rows[1]["content_hash"]


def test_evidence_projection_flows_into_workspace_memory(tmp_path: Path) -> None:
    """Phase-D UI closure: recording evidence mirrors the skill projection
    into workspace memory so all views see the capability ladder."""
    workspace_id = "workspace-evidence-projection-memory"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        attempt = start_attempt(client, workspace_id=workspace_id, card_id="card-1")

        evidence_resp = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": hashlib.sha256(b"artifact-one").hexdigest(),
                "result": "passed",
                "trust_level": "controlled_check",
            },
        )
        assert evidence_resp.status_code == 200, evidence_resp.text

        snapshot_memory = runtime.memory_service.snapshot(workspace_id)
        workspace_memory = snapshot_memory.workspace if isinstance(snapshot_memory.workspace, dict) else {}
        projection = workspace_memory.get("training_skill_projection")
        assert isinstance(projection, dict)
        assert projection["attempt_id"] == attempt["attempt_id"]
        dimensions = projection["dimensions"]
        assert set(dimensions) == {"comprehension", "implementation", "debugging", "transfer"}
        # A passed controlled check lifts implementation above not_verified.
        assert dimensions["implementation"]["state"] in {"assisted", "independent", "repeat_verified"}
        assert dimensions["implementation"]["verified_count"] >= 1


def test_resource_restore_clears_source_deleted_flags(tmp_path: Path) -> None:
    """TR-076 symmetry: delete flags citing evidence, restore un-flags it."""
    workspace_id = "workspace-evidence-restore"
    content = "# Restorable source\nEvidence cites this content.\n"
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        record = upload_resource(client, workspace_id=workspace_id, content=content)
        content_hash = record["content_hash"]
        assert content_hash

        attempt = start_attempt(client, workspace_id=workspace_id, card_id="card-1")
        evidence_resp = client.post(
            "/training/attempt/evidence",
            json={
                "attempt_id": attempt["attempt_id"],
                "artifact_hash": content_hash,
                "result": "passed",
            },
        )
        assert evidence_resp.status_code == 200, evidence_resp.text
        evidence_id = evidence_resp.json()["evidence"]["evidence_id"]

        deleted = client.post(
            "/resource/delete",
            json={"workspace_id": workspace_id, "resource_id": record["id"]},
        )
        assert deleted.status_code == 200, deleted.text
        evidence = find_evidence(runtime, attempt["attempt_id"], evidence_id)
        assert evidence["source_deleted"] is True

        restored = client.post(
            "/resource/restore",
            json={"workspace_id": workspace_id, "resource_id": record["id"]},
        )
        assert restored.status_code == 200, restored.text
        evidence = find_evidence(runtime, attempt["attempt_id"], evidence_id)
        assert evidence["source_deleted"] is False
        assert "source deleted" not in evidence["limitations"]
