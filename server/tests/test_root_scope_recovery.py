from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.core.models import TrainerRoot, UserProfile
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService
from app.planner.service import PlannerService
from app.workspace.provisioning import ProjectProvisioningService
from app.workspace.root_scope_recovery import recover_legacy_root_registrations


def _provision(repository: TrainerRepository, tmp_path: Path, root_id: str):
    root_path = tmp_path / root_id
    root_path.mkdir()
    project_path = tmp_path / f"project-{root_id}"
    project_path.mkdir()
    repository.register_trainer_root(TrainerRoot(
        rootId=root_id, rootPath=str(root_path), displayName=root_id,
    ))
    return ProjectProvisioningService(
        repository=repository, memory_service=MemoryService(repository),
        planner_service=PlannerService(repository),
    ).provision(
        project_path=str(project_path), project_name="Python practice",
        workspace_id=str(project_path), root_id=root_id, root_path=str(root_path),
    )


def test_root_recovery_preserves_current_learning_data_and_is_readonly_and_idempotent(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    other = _provision(legacy, tmp_path, "root-two")
    before = hashlib.sha256(legacy.database_path.read_bytes()).hexdigest()
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    profile = UserProfile(long_term_goal="My updated goal")
    current.save_profile(project.context_id, profile)
    current.save_structured_memory(project.context_id, {
        "workspace": {"response_language": "zh-CN", "latest_conversation": "New conversation"},
        "active_thread": {"summary": "Current work"},
    })
    current.save_session("new-session", project.context_id, {
        "session_id": "new-session", "workspace_id": project.context_id,
        "snapshot": {"messages": [{"id": "new-message", "content": "Keep this question"}]},
    })

    assert recover_legacy_root_registrations(current) == 1
    assert current.get_project_provisioning(project.context_id).project_id == project.project_id
    assert current.get_project_provisioning(other.context_id) is None
    assert current.get_profile(project.context_id).long_term_goal == "My updated goal"
    memory = current.load_structured_memory(project.context_id)
    assert memory["workspace"]["latest_conversation"] == "New conversation"
    assert memory["workspace"]["response_language"] == "zh-CN"
    assert memory["workspace"]["project_memory"]["id"] == project.project_memory_id
    assert memory["active_thread"]["summary"] == "Current work"
    assert current.load_session("new-session")["snapshot"]["messages"][0]["id"] == "new-message"
    assert current.load_session(project.agent_session_id) is not None
    service = ProjectProvisioningService(
        repository=current, memory_service=MemoryService(current),
        planner_service=PlannerService(current),
    )
    assert service.get(project.context_id).context_id == project.context_id
    assert recover_legacy_root_registrations(current) == 0
    assert hashlib.sha256(legacy.database_path.read_bytes()).hexdigest() == before


def test_custom_data_directories_do_not_import_unrelated_legacy_registrations(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    current = TrainerRepository(tmp_path / "custom" / "trainer.sqlite3")
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_project_context(project.context_id) is None


@pytest.mark.parametrize("conflict", ["root_path", "context_id", "root_id", "project_id"])
def test_recovery_does_not_replace_conflicting_scoped_identity(tmp_path, conflict):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    if conflict == "root_path":
        current.register_trainer_root(TrainerRoot(
            rootId="root-one", rootPath=str(tmp_path / "another-root"), displayName="Another root",
        ))
    else:
        current.save_structured_memory(project.context_id, {"workspace": {conflict: "another-id"}})
    current.save_profile(project.context_id, UserProfile(long_term_goal="Keep my current goal"))
    before_memory = current.load_structured_memory(project.context_id)
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_project_context(project.context_id) is None
    assert current.load_structured_memory(project.context_id) == before_memory
    assert current.get_profile(project.context_id).long_term_goal == "Keep my current goal"


def test_incomplete_legacy_registration_does_not_admit_a_project(tmp_path):
    legacy = TrainerRepository(tmp_path / "sidecar" / "trainer.sqlite3")
    project = _provision(legacy, tmp_path, "root-one")
    with legacy._connect() as connection:
        connection.execute("DELETE FROM sessions WHERE session_id = ?", (project.agent_session_id,))
    current = TrainerRepository(tmp_path / "sidecar" / "roots" / "root-one" / "trainer.sqlite3")
    assert recover_legacy_root_registrations(current) == 0
    assert current.get_trainer_root("root-one") is not None
    assert current.get_project_context(project.context_id) is None
    assert current.get_profile(project.context_id) is None
