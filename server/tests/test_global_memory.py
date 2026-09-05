from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.models import ResourceRecord
from app.core.settings import AppSettings
from app.db.repository import TrainerRepository
from app.main import create_app
from app.memory.service import MemoryService


def build_memory_service(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "trainer-memory.db"))


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Global Memory Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-global-memory.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_global_memory_persists_explicit_preferences_and_goals(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)

    updated = service.update_global_memory(
        preferences={" response_style ": " concise ", "language": "zh-CN"},
        long_term_goals=["Build reliable FastAPI services", "Build reliable FastAPI services", "Learn testing"],
    )

    restarted = build_memory_service(tmp_path).global_memory()

    assert updated.owner_id == "local-trainer"
    assert restarted.preferences == {"response_style": "concise", "language": "zh-CN"}
    assert restarted.long_term_goals == ["Build reliable FastAPI services", "Learn testing"]


def test_global_memory_excludes_workspace_resources_and_decisions(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    workspace_a = "project-a"
    workspace_b = "project-b"
    service.repository.save_resource(
        workspace_a,
        ResourceRecord(
            id="resource-a",
            kind="markdown",
            name="project-a-private-resource",
            source="project-a/private.md",
            summary="project-a-only-summary",
        ),
    )
    service.record_turn_memory(
        workspace_id=workspace_a,
        session_id="session-a",
        scenario="project",
        focus_area="project-a-focus",
        summary="project-a-private-summary",
        next_step="project-a-private-next-step",
        decision="project-a-private-decision",
        evidence=["project-a-private-evidence"],
    )
    service.update_global_memory(long_term_goals=["Become a reliable backend engineer"])

    snapshot_a = service.snapshot(workspace_a)
    snapshot_b = service.snapshot(workspace_b)
    assert snapshot_a.global_memory is not None
    assert snapshot_b.global_memory is not None
    assert [resource.id for resource in snapshot_a.resources] == ["resource-a"]
    assert snapshot_b.resources == []
    assert snapshot_a.global_memory == snapshot_b.global_memory

    global_payload = snapshot_a.global_memory.model_dump(by_alias=True, mode="json")
    assert set(global_payload) == {
        "ownerId",
        "preferences",
        "longTermGoals",
        "capabilityProfile",
        "growthHistory",
        "createdAt",
        "updatedAt",
    }
    global_text = json.dumps(global_payload, sort_keys=True)
    for private_value in (
        "project-a-private-resource",
        "project-a-private-summary",
        "project-a-private-decision",
        "project-a-private-evidence",
        "project-a-private-next-step",
    ):
        assert private_value not in global_text


def test_global_memory_only_records_verified_positive_outcomes(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)

    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="tests passed",
        verified_by_evaluator=False,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="",
        verified_by_evaluator=True,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="evaluation",
        verified_result="partial result",
        verified_by_evaluator=True,
    )
    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="repeated_error",
        verified_result="failed result",
        verified_by_evaluator=True,
    )

    before_verified_result = service.global_memory()
    assert before_verified_result.capability_profile == {}
    assert before_verified_result.growth_history == []

    service.record_learning_outcome(
        workspace_id="project-b",
        concepts=["API contracts", " API contracts "],
        outcome="tests_passed",
        verified_result="The evaluator confirmed the test suite passed.",
        verified_by_evaluator=True,
    )

    after_single_workspace = service.global_memory()
    assert after_single_workspace.capability_profile == {}
    assert after_single_workspace.growth_history == []

    service.record_learning_outcome(
        workspace_id="project-a",
        concepts=["API contracts"],
        outcome="tests_passed",
        verified_result="The evaluator confirmed the same contract in a second workspace.",
        verified_by_evaluator=True,
    )

    global_memory = service.global_memory()
    capability = global_memory.capability_profile["api contracts"]
    assert capability.concept == "API contracts"
    assert capability.verified_count == 1
    assert capability.last_outcome == "tests_passed"
    assert [(record.outcome, record.concepts) for record in global_memory.growth_history] == [
        ("tests_passed", ["API contracts"])
    ]


def test_global_memory_api_uses_camel_case_and_refreshes_snapshot(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        start = client.post(
            "/session/start",
            json={"workspace_id": "project-api", "workspace_name": "Project API"},
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        updated = client.post(
            "/memory/global",
            json={
                "sessionId": session_id,
                "workspaceId": "project-api",
                "preferences": {"responseStyle": "concise"},
                "longTermGoals": ["Master dependable API design"],
            },
        )
        assert updated.status_code == 200
        global_memory = updated.json()["memory"]["globalMemory"]
        assert global_memory["ownerId"] == "local-trainer"
        assert global_memory["preferences"] == {"responseStyle": "concise"}
        assert global_memory["longTermGoals"] == ["Master dependable API design"]

        fetched = client.get("/memory/global")
        assert fetched.status_code == 200
        assert fetched.json()["ownerId"] == "local-trainer"
        assert fetched.json()["longTermGoals"] == ["Master dependable API design"]
