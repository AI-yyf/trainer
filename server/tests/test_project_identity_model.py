from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import GlobalPlan, LearningPlan, UserProfile
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.main import create_app
from app.workspace.provisioning import ProjectProvisioningConflictError


def _repository(tmp_path: Path) -> TrainerRepository:
    return TrainerRepository(tmp_path / "identity.db")


def _runtime(tmp_path: Path):
    app = create_app(
        AppSettings(
            app_name="Trainer Identity Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="identity-runtime.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
    )
    return app.state.runtime


def _wait_for_adoption_completion(
    client: TestClient,
    *,
    workspace_id: str,
    root_path: Path,
    job_id: str,
    timeout_s: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(
            "/workspace/adoption-job",
            params={
                "workspace_id": workspace_id,
                "root_path": str(root_path),
                "job_id": job_id,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        status = payload["project_adoption_job"]["status"]
        if status == "completed":
            return payload
        if status in {"interrupted", "retry_required"}:
            raise AssertionError(f"adoption job did not complete: {payload['project_adoption_job']}")
        time.sleep(0.05)
    raise AssertionError("timed out waiting for project adoption to complete")


def test_one_root_creates_isolated_project_contexts(tmp_path: Path) -> None:
    root_path = tmp_path / "TrainerWorkspace"
    alpha_path = root_path / "Projects" / "alpha"
    beta_path = root_path / "Projects" / "beta"
    alpha_path.mkdir(parents=True)
    beta_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.repository.ensure_default_local_owner()
    runtime.repository.save_global_plan(
        GlobalPlan(
            id="global-identity-plan",
            owner_id="local-trainer",
            title="Long-term growth",
            summary="Keep separate projects connected to one growth record.",
        )
    )
    runtime.register_workspace_path("legacy-alpha", str(root_path))

    alpha = runtime.provision_project_adoption(
        workspace_id="legacy-alpha",
        root_path=str(root_path),
        project_path=str(alpha_path),
        project_name="alpha",
    )
    beta = runtime.provision_project_adoption(
        workspace_id="legacy-beta",
        root_id=alpha.root_id,
        project_path=str(beta_path),
        project_name="beta",
    )

    assert alpha.root_id == beta.root_id
    assert alpha.project_id != beta.project_id
    assert alpha.context_id != beta.context_id
    assert alpha.workspace_id == alpha.context_id
    assert beta.workspace_id == beta.context_id
    assert alpha.project_plan_id != beta.project_plan_id
    assert alpha.project_memory_id != beta.project_memory_id
    assert alpha.project_training_id != beta.project_training_id
    assert alpha.agent_session_id != beta.agent_session_id
    assert runtime.repository.resolve_context_id("legacy-alpha") == alpha.context_id
    assert runtime.repository.resolve_context_id("legacy-beta") == beta.context_id
    # Adoption records the global-plan identity, but must not invent a
    # project plan or a link before an explicit project-plan action.
    assert runtime.repository.get_global_plan_project_link(
        "global-identity-plan", alpha.context_id, alpha.project_plan_id
    ) is None
    assert runtime.repository.get_global_plan_project_link(
        "global-identity-plan", beta.context_id, beta.project_plan_id
    ) is None

    repeated = runtime.provision_project_adoption(
        workspace_id="legacy-alpha",
        context_id=alpha.context_id,
        root_id=alpha.root_id,
        root_path=str(root_path),
        project_path=str(alpha_path),
        project_name="alpha",
    )
    assert repeated.context_id == alpha.context_id
    assert runtime.resolve_workspace_path("legacy-alpha") == str(alpha_path.resolve())
    assert runtime.resolve_workspace_path("legacy-beta") == str(beta_path.resolve())


def test_provisioning_keeps_camel_case_json_aliases(tmp_path: Path) -> None:
    root_path = tmp_path / "workspace"
    project_path = root_path / "project"
    project_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-alias", str(root_path))

    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-alias",
        root_path=str(root_path),
        project_path=str(project_path),
        project_name="project",
    )

    payload = provisioning.model_dump(by_alias=True, mode="json")
    assert payload["workspaceId"] == provisioning.context_id
    assert payload["contextId"] == provisioning.context_id
    assert payload["rootId"] == provisioning.root_id
    assert payload["projectId"] == provisioning.project_id
    assert "workspace_id" not in payload
    assert "context_id" not in payload


def test_reconcile_root_and_project_location_preserves_identity(tmp_path: Path) -> None:
    root_path = tmp_path / "root-one"
    project_path = root_path / "project"
    moved_root_path = tmp_path / "root-two"
    moved_project_path = moved_root_path / "project-renamed"
    project_path.mkdir(parents=True)
    moved_project_path.mkdir(parents=True)
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-reconcile", str(root_path))
    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-reconcile",
        root_path=str(root_path),
        project_path=str(project_path),
        project_name="project",
    )

    root = runtime.reconcile_trainer_root(provisioning.root_id, str(moved_root_path))
    project = runtime.reconcile_project_location(
        root_id=provisioning.root_id,
        project_id=provisioning.project_id,
        project_path=str(moved_project_path),
        project_name="project-renamed",
    )
    restored = runtime.get_project_provisioning(provisioning.context_id)

    assert root.root_id == provisioning.root_id
    assert root.revision == 2
    assert str(root_path.resolve()) in root.path_history
    assert project.project_id == provisioning.project_id
    assert project.revision == 2
    assert str(project_path.resolve()) in project.path_history
    assert restored is not None
    assert restored.context_id == provisioning.context_id
    assert restored.root_path == str(moved_root_path.resolve())
    assert restored.project_path == str(moved_project_path.resolve())
    assert restored.root_revision == 2
    assert restored.project_revision == 2


def test_selected_trainer_root_and_external_project_keep_distinct_identities(tmp_path: Path) -> None:
    root_path = tmp_path / "root"
    external_project = tmp_path / "external-project"
    root_path.mkdir()
    external_project.mkdir()
    runtime = _runtime(tmp_path)
    runtime.register_workspace_path("legacy-root", str(root_path))
    provisioning = runtime.provision_project_adoption(
        workspace_id="legacy-root",
        root_path=str(root_path),
        project_path=str(external_project),
        project_name="external-project",
    )

    assert provisioning.root_path == str(root_path.resolve())
    assert provisioning.project_path == str(external_project.resolve())
    assert provisioning.root_path != provisioning.project_path

    with pytest.raises(ProjectProvisioningConflictError, match="must be different directories"):
        runtime.provision_project_adoption(
            workspace_id="legacy-invalid-root-project",
            root_id=provisioning.root_id,
            root_path=str(root_path),
            project_path=str(root_path),
            project_name="root-is-not-a-project",
        )


def test_identity_routes_expose_reconcile_state(tmp_path: Path) -> None:
    first_root = tmp_path / "first-root"
    first_project = first_root / "project"
    moved_root = tmp_path / "moved-root"
    moved_project = moved_root / "project"
    first_project.mkdir(parents=True)
    moved_project.mkdir(parents=True)
    app = create_app(
        AppSettings(
            app_name="Trainer Identity Route Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="identity-routes.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
    )
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime.register_workspace_path("legacy-route", str(first_root))
        provisioning = runtime.provision_project_adoption(
            workspace_id="legacy-route",
            root_path=str(first_root),
            project_path=str(first_project),
            project_name="project",
        )
        root_response = client.post(
            f"/workspace/roots/{provisioning.root_id}/reconcile",
            json={"rootId": provisioning.root_id, "rootPath": str(moved_root)},
        )
        assert root_response.status_code == 200
        root_identity = root_response.json()["root_identity"]
        assert root_identity["rootId"] == provisioning.root_id
        assert root_identity["pending"] is True
        assert root_identity["reconcile"]["pendingProjectIds"] == [provisioning.project_id]

        project_response = client.post(
            f"/workspace/projects/{provisioning.project_id}/reconcile",
            json={"rootId": provisioning.root_id, "projectPath": str(moved_project)},
        )
        assert project_response.status_code == 200
        identity = project_response.json()["project_identity"]
        assert identity["contextId"] == provisioning.context_id
        assert identity["canonicalProjectPath"] == str(moved_project.resolve())
        assert identity["pending"] is False
        assert identity["reconcile"]["project"]["state"] == "reconciled"

        identity_response = client.get("/workspace/identity", params={"workspace_id": "legacy-route"})
        assert identity_response.status_code == 200
        assert identity_response.json()["contextId"] == provisioning.context_id


def test_discovery_can_adopt_two_projects_under_one_root(tmp_path: Path) -> None:
    root_path = tmp_path / "workspace-root"
    alpha_path = root_path / "alpha"
    beta_path = root_path / "beta"
    alpha_path.mkdir(parents=True)
    beta_path.mkdir(parents=True)
    (alpha_path / "package.json").write_text('{"name":"alpha"}', encoding="utf-8")
    (beta_path / "package.json").write_text('{"name":"beta"}', encoding="utf-8")
    app = create_app(
        AppSettings(
            app_name="Trainer Multi Project Discovery Test",
            host="127.0.0.1",
            port=8765,
            data_dir=tmp_path,
            database_name="identity-discovery.db",
            default_session_stage="intake",
            summary_message_limit=6,
        )
    )
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime.register_workspace_path("legacy-alpha", str(root_path))
        alpha_discovery = client.post(
            "/workspace/classify",
            json={"workspace_id": "legacy-alpha", "folder_path": str(alpha_path)},
        )
        assert alpha_discovery.status_code == 200
        alpha_adoption = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "legacy-alpha",
                "discovery_id": alpha_discovery.json()["project_discovery"]["discovery_id"],
                "decision": "adopt",
            },
        )
        assert alpha_adoption.status_code == 200
        alpha_payload = alpha_adoption.json()
        if alpha_payload["project_adoption_job"]["status"] != "completed":
            alpha_payload = _wait_for_adoption_completion(
                client,
                workspace_id="legacy-alpha",
                root_path=root_path,
                job_id=alpha_payload["project_adoption_job"]["job_id"],
            )
        alpha = alpha_payload["project_identity"]

        beta_discovery = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "legacy-beta",
                "rootId": alpha["rootId"],
                "folder_path": str(beta_path),
            },
        )
        assert beta_discovery.status_code == 200
        beta_adoption = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "legacy-beta",
                "rootId": alpha["rootId"],
                "discovery_id": beta_discovery.json()["project_discovery"]["discovery_id"],
                "decision": "adopt",
            },
        )
        assert beta_adoption.status_code == 200
        beta_payload = beta_adoption.json()
        if beta_payload["project_adoption_job"]["status"] != "completed":
            beta_payload = _wait_for_adoption_completion(
                client,
                workspace_id="legacy-beta",
                root_path=root_path,
                job_id=beta_payload["project_adoption_job"]["job_id"],
            )
        beta = beta_payload["project_identity"]

    assert alpha["rootId"] == beta["rootId"]
    assert alpha["projectId"] != beta["projectId"]
    assert alpha["contextId"] != beta["contextId"]
    assert alpha["idempotency"]["state"] == "created"
    assert beta["idempotency"]["state"] == "created"


def test_legacy_workspace_provisioning_migrates_to_context_alias(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-identity.db"
    legacy_path = str((tmp_path / "legacy-project").resolve())
    legacy_profile = UserProfile(long_term_goal="Keep the legacy project recoverable.")
    legacy_plan = LearningPlan(id="legacy-plan", title="Legacy project plan")
    legacy_payload = {
        "workspace_id": "legacy-workspace",
        "project_id": "legacy-project-id",
        "project_path": legacy_path,
        "project_name": "legacy-project",
        "project_memory_id": "legacy-memory",
        "project_plan_id": "legacy-plan",
        "project_training_id": "legacy-training",
        "project_agent_context_id": "legacy-agent-context",
        "agent_session_id": "legacy-session",
    }
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE project_provisionings (
                workspace_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            );
            CREATE TABLE user_profile (workspace_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE learning_plan (
                plan_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE structured_memory (workspace_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO project_provisionings (workspace_id, project_id, payload) VALUES (?, ?, ?)",
            ("legacy-workspace", "legacy-project-id", json.dumps(legacy_payload)),
        )
        connection.execute(
            "INSERT INTO user_profile (workspace_id, payload) VALUES (?, ?)",
            ("legacy-workspace", legacy_profile.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO learning_plan (plan_id, workspace_id, payload) VALUES (?, ?, ?)",
            (legacy_plan.id, "legacy-workspace", legacy_plan.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO structured_memory (workspace_id, payload) VALUES (?, ?)",
            ("legacy-workspace", json.dumps({"workspace": {"workspace_id": "legacy-workspace"}})),
        )
        connection.execute(
            "INSERT INTO sessions (session_id, workspace_id, payload) VALUES (?, ?, ?)",
            (
                "legacy-session",
                "legacy-workspace",
                json.dumps({"session_id": "legacy-session", "workspace_id": "legacy-workspace", "snapshot": {}}),
            ),
        )

    repository = TrainerRepository(database_path)
    context_id = repository.resolve_context_id("legacy-workspace")
    provisioning = repository.get_project_provisioning("legacy-workspace")

    assert context_id is not None
    assert provisioning is not None
    assert provisioning.context_id == context_id
    assert provisioning.workspace_id == context_id
    assert provisioning.legacy_workspace_id == "legacy-workspace"
    assert repository.get_profile(context_id) is not None
    assert repository.get_plan_by_id("legacy-plan") is not None
    assert repository.get_plan_by_id("legacy-plan")[0] == context_id
    assert repository.load_session("legacy-session")["workspace_id"] == context_id
    assert repository.load_structured_memory(context_id)["workspace"]["workspace_id"] == context_id
