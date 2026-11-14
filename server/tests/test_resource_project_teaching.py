"""Resources, project knowledge and skills must participate in teaching/return.

Failure-first coverage:
* a card-bound evaluation cites the current resource version (id/hash/location);
* a resource version change makes old evidence stale and removes it from the
  capability projection until re-verified;
* a distilled project skill is marked stale on source change and excluded from
  agent selection, then becomes ready again after re-distillation;
* skill usage remains usage, never learner mastery.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.core.models import (
    EvaluationCheck,
    EvaluationReport,
    TrainingCardCandidateSnapshot,
)
from app.skills.registry import SkillRegistry
from app.skills.runtime import record_skill_usage, select_active_skills
from app.training.attempt_store import AttemptStore
from app.training.skill_projection import project_skills
from tests.test_api import build_client


def _passed_report() -> EvaluationReport:
    return EvaluationReport(
        passed=True,
        summary="1 test passed",
        next_step="Reflect",
        reflection="",
        dynamic_checks=[
            EvaluationCheck(id="pytest", label="pytest", status="passed", detail="1 passed")
        ],
    )


def test_card_evaluation_cites_current_resource_version(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-resource-provenance"
        session = client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Resource provenance"},
        ).json()["session_id"]
        from app.core.models import ResourceUploadRequest

        resource = runtime.resource_service.upload(
            workspace,
            ResourceUploadRequest(
                kind="text",
                name="queue-lock-paper",
                source="queue-lock.md",
                content="# Queue locks\n\nA lock protects the write path.",
            ),
        )
        version = runtime.resource_version_store.current_version(workspace, resource.id)
        assert version is not None
        path = str(tmp_path / "sample.py")
        card = TrainingCardCandidateSnapshot(
            card_id="card-resource",
            card_type="practice",
            status="active",
            title="Apply the queue lock",
            focus_area="queue lock",
            files_to_touch=[path],
            resource_id=resource.id,
        )
        runtime.memory_service.upsert_card(workspace, card)
        runtime.memory_service.update_workspace_state(workspace, selected_card_id=card.card_id)
        runtime.evaluator_service.evaluate_current_file = MagicMock(return_value=_passed_report())
        response = client.post(
            "/evaluate/current-file",
            json={
                "workspace_id": workspace,
                "session_id": session,
                "evaluation_source": "training",
                "training_card_id": card.card_id,
                "training_phase": "verify",
                "file_path": path,
                "content": "def test_boundary():\n    assert True\n",
                "language_id": "python",
            },
        )
        assert response.status_code == 200, response.text
        attempts = runtime.attempt_store.list_attempts(workspace_id=workspace, card_id=card.card_id)
        evidence = runtime.attempt_store.list_evidence(attempts[-1]["attempt_id"])
        current = next(item for item in evidence if item.get("is_current"))
        assert current["resource_id"] == resource.id
        assert current["resource_version_id"] == version["version_id"]
        assert current["resource_content_hash"] == version["content_hash"]
        assert current["resource_location"] == version["location"]


def test_resource_version_change_stales_old_evidence_until_reverified(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card", assistance_level="none")
    evidence = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_version_id="rv-1",
        resource_content_hash="old-hash",
        resource_location={"path": "papers/queue.md"},
    )
    assert evidence is not None
    assert project_skills(store.list_evidence(attempt["attempt_id"]))["implementation"]["state"] == "independent"

    marked = store.mark_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="new-hash",
    )
    assert marked == 1
    stale = store.list_evidence(attempt["attempt_id"])[0]
    assert stale["source_stale"] is True
    assert stale["source_stale_reason"] == "resource_version_changed"
    assert stale["is_current"] is False
    assert project_skills([stale])["implementation"]["state"] == "not_verified"

    # A verified citation for the new version is live.
    updated = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_version_id="rv-2",
        resource_content_hash="new-hash",
        resource_location={"path": "papers/queue.md"},
    )
    assert updated is not None
    current = next(
        item for item in store.list_evidence(attempt["attempt_id"]) if item.get("is_current")
    )
    assert current["resource_content_hash"] == "new-hash"
    assert project_skills([current])["implementation"]["state"] == "independent"


def test_same_resource_version_restore_clears_stale_flag(tmp_path: Path) -> None:
    store = AttemptStore(tmp_path / "attempts.db")
    attempt = store.start_attempt(workspace_id="ws", card_id="card")
    store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="artifact-hash",
        result="passed",
        resource_id="resource-paper",
        resource_content_hash="same-hash",
    )
    store.mark_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="other-hash",
    )
    cleared = store.clear_evidence_resource_version_stale(
        workspace_id="ws",
        resource_id="resource-paper",
        current_content_hash="same-hash",
    )
    assert cleared == 1
    evidence = store.list_evidence(attempt["attempt_id"])[0]
    assert evidence["source_stale"] is False
    assert evidence["is_current"] is True


def test_project_skill_stales_on_source_change_and_reactivates_on_redistill(
    tmp_path: Path,
) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    metadata = {
        "origin": "project-analysis",
        "source_resource_id": "resource-project",
        "source_content_hash": "old-content",
        "commit_sha": "commit-1",
        "front_matter": {"triggers": "项目结构, 架构, call graph"},
    }
    record, created = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Modules, entry points and call graph.",
        body="项目结构：modules and calls.",
        metadata=metadata,
        workspace_id="ws",
    )
    assert created is True and record.active is True
    assert any(
        skill.skill_id == record.skill_id
        for skill in select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws")
    )

    # Same source content: no stale flag.
    assert (
        registry.mark_project_skill_stale_for_content(
            workspace_id="ws",
            resource_id="resource-project",
            current_content_hash="old-content",
        )
        == 0
    )
    assert record.active is True

    # New source content: stale, inactive, excluded from agent selection.
    assert (
        registry.mark_project_skill_stale_for_content(
            workspace_id="ws",
            resource_id="resource-project",
            current_content_hash="new-content",
        )
        == 1
    )
    assert record.active is False
    assert record.status() == "stale"
    assert select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws") == []

    refreshed, created_again = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Modules, entry points and call graph.",
        body="项目结构：modules and calls.",
        metadata={**metadata, "source_content_hash": "new-content"},
        workspace_id="ws",
    )
    assert created_again is False
    assert refreshed.active is True
    assert refreshed.metadata.get("stale") is None
    assert refreshed.status() == "ready"
    assert any(
        skill.skill_id == refreshed.skill_id
        for skill in select_active_skills(registry, "帮我理解项目结构和架构", workspace_id="ws")
    )


def test_resource_reindex_stales_old_evidence_and_project_skill(tmp_path: Path) -> None:
    from app.core.models import ResourceUploadRequest
    from app.skills.runtime import runtime_skill_registry

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        workspace = "ws-resource-reindex"
        client.post(
            "/session/start",
            json={"workspace_id": workspace, "workspace_name": "Reindex"},
        )
        resource = runtime.resource_service.upload(
            workspace,
            ResourceUploadRequest(
                kind="text",
                name="queue-notes",
                source="queue-notes.md",
                content="v1: the queue lock protects writes.",
            ),
        )
        first = client.post(
            "/resource/index",
            json={"workspace_id": workspace, "resource_id": resource.id},
        )
        assert first.status_code == 200, first.text
        old_version = runtime.resource_version_store.current_version(workspace, resource.id)
        assert old_version is not None

        attempt = runtime.attempt_store.start_attempt(
            workspace_id=workspace, card_id="card-cited"
        )
        runtime.attempt_store.record_evidence(
            attempt_id=attempt["attempt_id"],
            artifact_hash="artifact",
            result="passed",
            resource_id=resource.id,
            resource_version_id=old_version["version_id"],
            resource_content_hash=old_version["content_hash"],
            resource_location=old_version["location"],
        )
        registry = runtime_skill_registry(runtime)
        skill, _ = registry.upsert_knowledge_skill(
            skill_id="queue-project-knowledge",
            name="Queue project knowledge",
            description="Queue lock architecture.",
            body="项目结构：queue lock.",
            metadata={
                "origin": "project-analysis",
                "source_resource_id": resource.id,
                "source_content_hash": "stale-hash",
                "commit_sha": "commit-1",
                "front_matter": {"triggers": "项目结构"},
            },
            workspace_id=workspace,
        )
        assert skill.active is True

        Path(resource.source).write_text(
            "v2: the queue lock also guards the read path.", encoding="utf-8"
        )
        second = client.post(
            "/resource/index",
            json={"workspace_id": workspace, "resource_id": resource.id},
        )
        assert second.status_code == 200, second.text

        stale_evidence = runtime.attempt_store.list_evidence(attempt["attempt_id"])[0]
        assert stale_evidence["source_stale"] is True
        assert stale_evidence["is_current"] is False
        refreshed = registry._skills[skill.skill_id]
        assert refreshed.metadata.get("stale") is True
        assert refreshed.active is False


def test_skill_usage_feedback_is_not_learner_mastery(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills")
    record, _ = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Project structure.",
        body="项目结构。",
        metadata={
            "origin": "project-analysis",
            "source_resource_id": "resource-project",
            "front_matter": {"triggers": "项目结构"},
        },
        workspace_id="ws",
    )
    registry.record_usage(
        record.skill_id,
        applied=True,
        workspace_id="ws",
        session_id="session-1",
        evidence={"basis": "contract_markers"},
    )
    refreshed = registry._skills[record.skill_id]
    assert refreshed.metadata["usage_count"] == 1
    assert refreshed.metadata["applied_count"] == 1
    assert "mastery" not in refreshed.metadata


def test_record_skill_usage_writes_registry_facts_only(tmp_path: Path) -> None:
    class Runtime:
        skill_registry = SkillRegistry(tmp_path / "skills")

    registry = Runtime.skill_registry
    record, _ = registry.upsert_knowledge_skill(
        skill_id="project-knowledge",
        name="Project knowledge",
        description="Project structure.",
        body="项目结构。",
        metadata={
            "origin": "project-analysis",
            "source_resource_id": "resource-project",
            "front_matter": {"triggers": "项目结构"},
        },
        workspace_id="ws",
    )
    selected = select_active_skills(registry, "项目结构是什么", workspace_id="ws")
    assert selected
    usages = record_skill_usage(
        Runtime(),
        "ws",
        "session-1",
        selected,
        stop_reason="completed",
        final_content=f"Used {record.skill_id}: modules.",
        tool_events=[],
    )
    assert usages and usages[0]["skill_id"] == record.skill_id
    assert registry._skills[record.skill_id].metadata["usage_count"] == 1
