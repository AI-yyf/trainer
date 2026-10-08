from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_project_provisioning import _client

from app.workspace.remote_identity import canonical_remote_project_uri


def _payload(client, root: Path, uri: str, *, alias: str = "remote-owned") -> dict:
    root.mkdir(exist_ok=True)
    identity = client.app.state.runtime.register_trainer_root(root_id=None, root_path=str(root))
    return {
        "workspace_id": alias,
        "root_id": identity.root_id,
        "root_path": str(root),
        "project_name": "Owned remote project",
        "workspace_trusted": True,
        "remote_project": {
            "protocol_version": 2,
            "directory": True,
            "workspace_uri": uri,
            "canonical_uri": uri,
            "remote_name": "ssh-remote",
        },
    }


def test_remote_admission_is_durable_local_and_idempotent(tmp_path: Path) -> None:
    uri = "vscode-remote://ssh-remote+owned/tmp/project-a"
    with _client(tmp_path) as client:
        payload = _payload(client, tmp_path / "brain", uri)
        admitted = client.post("/workspace/remote/adopt", json=payload)
        assert admitted.status_code == 200, admitted.text
        provisioning = admitted.json()["project_provisioning"]
        repeated = client.post("/workspace/remote/adopt", json=payload)
        assert repeated.status_code == 200
        assert repeated.json()["project_provisioning"] == provisioning
        runtime = client.app.state.runtime
        assert runtime.resolve_workspace_path(provisioning["context_id"]) == uri
        workspace = runtime.memory_service.snapshot(provisioning["context_id"]).workspace
        assert workspace["remote_workspace_uri"] == uri
        assert workspace["remote_name"] == "ssh-remote"
        authority = runtime.workspace_authority(provisioning["context_id"])
        assert authority.active_workspace_root is None
        assert runtime.repository.get_latest_plan(provisioning["context_id"]) is None
        assert not (tmp_path / "vscode-remote:").exists()
    with _client(tmp_path) as restarted:
        restored = restarted.app.state.runtime.get_project_provisioning(provisioning["context_id"])
        assert restored.model_dump(mode="json") == provisioning
        assert restarted.app.state.runtime.workspace_authority(restored.context_id).active_workspace_root is None


def test_remote_contexts_isolate_authority_project_and_local_root(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        requests = [
            ("ssh-remote+owned", "project-a", "brain-a"),
            ("ssh-remote+owned", "project-b", "brain-a"),
            ("ssh-remote+other", "project-a", "brain-a"),
            ("ssh-remote+owned", "project-a", "brain-b"),
        ]
        contexts = []
        for i, (authority, project, brain) in enumerate(requests):
            payload = _payload(client, tmp_path / brain, f"vscode-remote://{authority}/tmp/{project}", alias=f"remote-{i}")
            response = client.post("/workspace/remote/adopt", json=payload)
            assert response.status_code == 200, response.text
            contexts.append(response.json()["project_provisioning"])
        for key in ("project_id", "context_id", "project_memory_id", "project_training_id", "agent_session_id"):
            assert len({item[key] for item in contexts}) == 4
        runtime = client.app.state.runtime
        runtime.memory_service.update_workspace_state(contexts[0]["context_id"], owned_note="only a")
        for other in contexts[1:]:
            assert "owned_note" not in runtime.memory_service.snapshot(other["context_id"]).workspace


@pytest.mark.parametrize("change", ["untrusted", "foreign_authority", "non_directory", "protocol", "root_mismatch"])
def test_remote_admission_rejects_unobserved_or_mismatched_identity(tmp_path: Path, change: str) -> None:
    with _client(tmp_path) as client:
        payload = _payload(client, tmp_path / "brain", "vscode-remote://ssh-remote+owned/tmp/project")
        if change == "untrusted":
            payload["workspace_trusted"] = False
        elif change == "foreign_authority":
            payload["remote_project"]["canonical_uri"] = "vscode-remote://ssh-remote+foreign/tmp/project"
        elif change == "non_directory":
            payload["remote_project"]["directory"] = False
        elif change == "protocol":
            payload["remote_project"]["protocol_version"] = 1
        else:
            payload["root_path"] = str(tmp_path / "different")
        response = client.post("/workspace/remote/adopt", json=payload)
        assert response.status_code in {403, 409}
        assert client.app.state.runtime.repository.get_project_provisioning("remote-owned") is None


def test_remote_bundle_failure_rolls_back_all_project_state(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        payload = _payload(client, tmp_path / "brain", "vscode-remote://ssh-remote+owned/tmp/project")
        repository = client.app.state.runtime.repository
        # Fail after identity/profile/memory inserts, while the session is saved.
        with repository._connect() as connection:
            connection.execute("CREATE TRIGGER fail_owned_session BEFORE INSERT ON sessions BEGIN SELECT RAISE(ABORT, 'owned failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="owned failure"):
            client.post("/workspace/remote/adopt", json=payload)
        with repository._connect() as connection:
            for table in ("trainer_projects", "project_contexts", "structured_memory", "sessions", "user_profile"):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert repository.get_project_provisioning("remote-owned") is None


@pytest.mark.parametrize("uri", [
    "file:///tmp/project", "vscode-remote://ssh-remote+owned/tmp/../outside",
    "vscode-remote://ssh-remote+owned/tmp/%2e%2e/outside",
    "vscode-remote://ssh-remote+owned/tmp/project?token=secret",
    "vscode-remote://user@ssh-remote+owned/tmp/project",
])
def test_remote_identity_rejects_ambiguous_or_credential_uris(uri: str) -> None:
    with pytest.raises(ValueError):
        canonical_remote_project_uri(uri)
