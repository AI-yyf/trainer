from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import (
    GlobalPlan,
    LearningPlan,
    ProjectContext,
    TrainerProject,
    TrainerRoot,
    UserProfile,
)
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Provisioning Test",
                host="127.0.0.1",
                port=8765,
                data_dir=tmp_path,
                database_name="trainer-provisioning-test.db",
                default_session_stage="intake",
                summary_message_limit=6,
            )
        )
    )


def _wait_for_project_adoption(
    client: TestClient,
    *,
    workspace_id: str,
    root_path: Path,
    job_id: str,
    timeout_s: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    root_path_str = str(root_path)
    while time.monotonic() < deadline:
        status = client.get(
            "/workspace/adoption-job",
            params={
                "workspace_id": workspace_id,
                "root_path": root_path_str,
                "job_id": job_id,
            },
        )
        assert status.status_code == 200, status.text
        payload = status.json()
        job = payload["project_adoption_job"]
        if job["status"] == "completed":
            return payload
        if job["status"] in {"interrupted", "retry_required"}:
            raise AssertionError(f"adoption job did not complete: {job}")
        time.sleep(0.05)
    raise AssertionError("timed out waiting for project adoption to complete")


def _adopt(client: TestClient, workspace_id: str, project_path: Path) -> dict[str, object]:
    runtime = client.app.state.runtime
    runtime.register_workspace_path(workspace_id, str(project_path.parent))
    classified = client.post(
        "/workspace/classify",
        json={
            "workspace_id": workspace_id,
            "folder_path": str(project_path),
            "root_path": str(project_path.parent),
        },
    )
    assert classified.status_code == 200
    discovery_id = classified.json()["project_discovery"]["discovery_id"]
    adopted = client.post(
        "/workspace/discovery/decision",
        json={
            "workspace_id": workspace_id,
            "discovery_id": discovery_id,
            "decision": "adopt",
            "root_path": str(project_path.parent),
        },
    )
    assert adopted.status_code == 200
    payload = adopted.json()
    job = payload["project_adoption_job"]
    if job["status"] != "completed":
        payload = _wait_for_project_adoption(
            client,
            workspace_id=workspace_id,
            root_path=project_path.parent,
            job_id=job["job_id"],
        )
    return payload


def test_adoption_is_idempotent_and_survives_runtime_restart(tmp_path: Path) -> None:
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"provisioned-project"}', encoding="utf-8")

    with _client(tmp_path) as client:
        first = _adopt(client, "workspace-provisioned", project)
        discovery_id = first["project_discovery"]["discovery_id"]
        repeated = client.post(
            "/workspace/discovery/decision",
            json={"workspace_id": "workspace-provisioned", "discovery_id": discovery_id, "decision": "adopt"},
        )
        assert repeated.status_code == 200
        second = repeated.json()
        assert second["project_provisioning"] == first["project_provisioning"]

    with _client(tmp_path) as restarted:
        lookup = restarted.get(
            "/workspace/project-provisioning",
            params={"workspace_id": "workspace-provisioned"},
        )
        assert lookup.status_code == 200
        provisioning = lookup.json()["project_provisioning"]
        assert provisioning == first["project_provisioning"]
        runtime = restarted.app.state.runtime
        restored = runtime.ensure_session(
            provisioning["agent_session_id"],
            workspace_id="workspace-provisioned",
        )
        assert restored.session_id == provisioning["agent_session_id"]
        assert restored.snapshot.plan in (None, {})
        assert runtime.repository.get_latest_plan(provisioning["context_id"]) is None
        assert runtime.resolve_workspace_path("workspace-provisioned") == str(project.resolve())


def test_adoption_job_becomes_retry_required_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"retry-project"}', encoding="utf-8")

    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-retry", str(project.parent))
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-retry",
                "folder_path": str(project),
                "root_path": str(project.parent),
            },
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]

        ready = threading.Event()
        original_scan = runtime.project_adoption_index_service._scan_project

        def slow_scan(project_path: str) -> dict[str, object]:
            ready.wait(timeout=2.0)
            return original_scan(project_path)

        monkeypatch.setattr(runtime.project_adoption_index_service, "_scan_project", slow_scan)

        adopted = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-retry",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(project.parent),
            },
        )
        assert adopted.status_code == 200
        job = adopted.json()["project_adoption_job"]

        with _client(tmp_path) as restarted:
            status = restarted.get(
                "/workspace/adoption-job",
                params={
                    "workspace_id": "workspace-retry",
                    "root_path": job["root_path"],
                    "job_id": job["job_id"],
                },
            )
            assert status.status_code == 200
            assert status.json()["project_adoption_job"]["status"] == "retry_required"

        ready.set()


def test_adoption_interrupts_when_the_project_disappears_before_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"vanished-project"}', encoding="utf-8")

    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-vanished", str(project.parent))
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-vanished",
                "folder_path": str(project),
                "root_path": str(project.parent),
            },
        )
        assert classified.status_code == 200
        discovery_id = classified.json()["project_discovery"]["discovery_id"]

        ready = threading.Event()
        original_scan = runtime.project_adoption_index_service._scan_project

        def delayed_scan(project_path: str) -> dict[str, object]:
            ready.wait(timeout=2.0)
            return original_scan(project_path)

        monkeypatch.setattr(runtime.project_adoption_index_service, "_scan_project", delayed_scan)

        adopted = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-vanished",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(project.parent),
            },
        )
        assert adopted.status_code == 200
        job = adopted.json()["project_adoption_job"]

        shutil.rmtree(project)
        ready.set()

        deadline = time.monotonic() + 3.0
        status_payload: dict[str, object] | None = None
        while time.monotonic() < deadline:
            status = client.get(
                "/workspace/adoption-job",
                params={
                    "workspace_id": "workspace-vanished",
                    "root_path": job["root_path"],
                    "job_id": job["job_id"],
                },
            )
            assert status.status_code == 200, status.text
            status_payload = status.json()
            if status_payload["project_adoption_job"]["status"] not in {"queued", "running"}:
                break
            time.sleep(0.05)

        assert status_payload is not None
        interrupted = status_payload["project_adoption_job"]
        assert interrupted["status"] == "interrupted"
        assert interrupted["inventory"]["message"] == "Project path is no longer available."
        assert runtime.get_project_provisioning("workspace-vanished") is None


def test_adoption_rejects_using_the_trainer_root_as_the_project_path(tmp_path: Path) -> None:
    root = tmp_path / "trainer-root"
    root.mkdir()

    with _client(tmp_path) as client:
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-invalid-root-project",
                "folder_path": str(root),
                "root_path": str(root),
            },
        )
        assert classified.status_code == 200
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        rejected = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-invalid-root-project",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(root),
            },
        )

    assert rejected.status_code == 409
    assert "different managed project" in rejected.json()["detail"]


def test_session_start_rejects_adopted_project_missing_structured_memory(tmp_path: Path) -> None:
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"broken-project"}', encoding="utf-8")

    with _client(tmp_path) as client:
        adopted = _adopt(client, "workspace-missing-structured-memory", project)
        context_id = adopted["project_provisioning"]["context_id"]
        repository = client.app.state.runtime.repository
        with sqlite3.connect(repository.database_path) as connection:
            connection.execute(
                "DELETE FROM structured_memory WHERE workspace_id = ?",
                (context_id,),
            )

        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-missing-structured-memory",
                "workspace_name": "Missing structured memory",
            },
        )

    assert started.status_code == 409
    detail = started.json()["detail"]
    assert detail["state"] == "repair_required"
    assert detail["recoverable"] is True
    assert "structured memory" in detail["next_step"]


def test_project_bundle_rolls_back_when_plan_identity_conflicts(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "rollback.db")
    conflicting_plan = LearningPlan(id="project-plan-conflict", title="Existing plan")
    repository.save_plan("other-workspace", conflicting_plan)
    root = TrainerRoot(
        root_id="root-conflict",
        root_path=str(tmp_path / "root"),
        display_name="root",
    )
    project = TrainerProject(
        project_id="project-conflict",
        root_id=root.root_id,
        project_path=str(tmp_path / "project"),
        project_name="project",
    )
    context = ProjectContext(
        context_id="context-conflict",
        root_id=root.root_id,
        project_id=project.project_id,
        project_memory_id="project-memory-conflict",
        project_plan_id="project-plan-conflict",
        project_training_id="project-training-conflict",
        project_agent_context_id="project-agent-conflict",
        agent_session_id="session-project-conflict",
        legacy_workspace_id="target-workspace",
    )

    with pytest.raises(sqlite3.IntegrityError):
        repository.create_project_context_bundle(
            root=root,
            project=project,
            context=context,
            profile=UserProfile(long_term_goal="Project goal"),
            plan=conflicting_plan,
            structured_memory={"workspace": {"project_id": project.project_id}},
            session_payload={
                "session_id": context.agent_session_id,
                "workspace_id": context.context_id,
                "workspace_name": project.project_name,
                "snapshot": {},
            },
        )

    assert repository.get_profile(context.context_id) is None
    assert repository.load_structured_memory(context.context_id) is None
    assert repository.load_session(context.agent_session_id) is None
    assert repository.get_trainer_root(root.root_id) is None
    assert repository.get_trainer_project(project.project_id) is None
    assert repository.get_project_provisioning(context.context_id) is None


def test_adoption_does_not_auto_generate_a_learning_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "workspace" / "auth-expiry-lab"
    project.mkdir(parents=True)
    (project / "auth.py").write_text(
        "def require_fresh_token(token):\n    if not token:\n        raise ValueError('expired')\n    return token\n",
        encoding="utf-8",
    )

    with _client(tmp_path) as client:
        runtime = client.app.state.runtime
        generate_calls: list[object] = []
        original_generate = runtime.planner_service.generate_plan

        def _track_generate(request: object) -> object:
            generate_calls.append(request)
            return original_generate(request)

        monkeypatch.setattr(runtime.planner_service, "generate_plan", _track_generate)
        adopted = _adopt(client, "workspace-no-invented-plan", project)
        provisioning = adopted["project_provisioning"]
        context_id = provisioning["context_id"]
        session_id = provisioning["agent_session_id"]

        assert generate_calls == []
        assert runtime.repository.get_latest_plan(context_id) is None
        assert runtime.repository.get_plan_by_id(provisioning["project_plan_id"]) is None
        restored = runtime.ensure_session(session_id, workspace_id=context_id)
        assert restored.snapshot.plan in (None, {})
        assert restored.snapshot.current_task is None

        memory = runtime.memory_service.snapshot(context_id)
        understanding = memory.workspace_understanding
        first_look = understanding.first_look_summary if understanding is not None else None
        assert first_look is not None
        first_look_next = str(first_look.recommended_next_step or "").strip()
        first_look_why = str(first_look.why_this_guess or "").strip()
        assert first_look_next
        from app.pedagogy.plan_orientation import derive_plan_orientation

        plan_orientation = derive_plan_orientation(
            has_formal_plan=False,
            first_look_recommended_next=first_look_next,
            first_look_why=first_look_why,
            language="en-US",
        )
        assert plan_orientation.get("primary_action") == "continue_without_plan"
        assert plan_orientation.get("primary_action") != "generate_plan"
        assert plan_orientation.get("next_step") == first_look_next

        generated = client.post(
            "/plan/generate",
            json={
                "session_id": session_id,
                "workspace_id": context_id,
                "goals": ["Build one verified auth expiry check"],
            },
        )
        assert generated.status_code == 400, generated.text
        assert generate_calls == []
        assert runtime.repository.get_latest_plan(context_id) is None
        assert restored.snapshot.current_task in (None, {})


def test_adoption_records_global_plan_without_inventing_a_project_plan(tmp_path: Path) -> None:
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)

    with _client(tmp_path) as client:
        repository = client.app.state.runtime.repository
        repository.ensure_default_local_owner()
        repository.save_global_plan(
            GlobalPlan(
                id="global-plan-test",
                owner_id="local-trainer",
                title="Growth plan",
                summary="Keep project work connected to long-term growth.",
            )
        )
        adopted = _adopt(client, "workspace-global-link", project)
        provisioning = adopted["project_provisioning"]
        assert provisioning["global_plan_id"] == "global-plan-test"
        assert repository.get_latest_plan(provisioning["context_id"]) is None
        assert repository.get_global_plan_project_link(
            "global-plan-test",
            provisioning["context_id"],
            provisioning["project_plan_id"],
        ) is None
        generated = client.post(
            "/plan/generate",
            json={
                "session_id": provisioning["agent_session_id"],
                "workspace_id": provisioning["context_id"],
                "goals": ["Keep project work connected to long-term growth."],
            },
        )
        assert generated.status_code == 400, generated.text
        assert repository.get_latest_plan(provisioning["context_id"]) is None
        assert repository.get_global_plan_project_link(
            "global-plan-test",
            provisioning["context_id"],
            provisioning["project_plan_id"],
        ) is None
