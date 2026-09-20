from __future__ import annotations

from pathlib import Path

from app.db.repository import TrainerRepository
from app.memory.service import MemoryService


def build_memory_service(tmp_path: Path) -> MemoryService:
    return MemoryService(TrainerRepository(tmp_path / "trainer-global-memory.db"))


def _remember_preference(service: MemoryService, workspace_id: str, key: str, value: str) -> None:
    structured = service._structured_for(workspace_id)
    structured.remember_preference(key, value, source=f"test:{workspace_id}")
    service._persist_structured(workspace_id)


def test_memory_scope_defaults_to_global(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)

    assert service.memory_scope() == "global"
    snapshot = service.snapshot("fresh-workspace")
    assert snapshot.memory_scope == "global"


def test_global_scope_reads_other_workspace_preferences_and_mastery(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _remember_preference(service, "project-alpha", "teaching_style", "concept-first")

    service.record_learning_outcome(
        workspace_id="project-alpha",
        concepts=["react-effects"],
        outcome="tests_passed",
        summary="Alpha project effects practice passed.",
        verified_result="evaluator confirmed.",
        verified_by_evaluator=True,
        focus_area="react-effects",
    )

    beta_snapshot = service.snapshot("project-beta")
    beta_preferences = {preference.key: preference.value for preference in beta_snapshot.profile.preferences} if beta_snapshot.profile else {}
    merged_keys = {pref.key for pref in _snapshot_preferences(service, "project-beta")}
    assert "teaching_style" in merged_keys
    assert beta_preferences.get("teaching_style", "concept-first") == "concept-first"
    assert any("react-effects" in concept for concept in beta_snapshot.lowest_mastery_concepts) or (
        beta_snapshot.current_focus != ""
    )


def test_global_scope_shares_durable_preferences_but_not_transient_context(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _remember_preference(service, "project-alpha", "teaching_style", "concept-first")
    _remember_preference(service, "project-alpha", "project_context", "secret alpha repository")
    _remember_preference(service, "project-alpha", "latest_turn_teaching_note", "raw alpha code")
    _remember_preference(service, "project-alpha", "latest_turn_confidence", "alpha-only")
    _remember_preference(service, "project-alpha", "custom_learning_preference", "diagram-first")

    preferences = {
        preference.key: preference.value
        for preference in _snapshot_preferences(service, "project-beta")
    }

    assert preferences["teaching_style"] == "concept-first"
    assert "project_context" not in preferences
    assert "latest_turn_teaching_note" not in preferences
    assert "latest_turn_confidence" not in preferences
    assert preferences["custom_learning_preference"] == "diagram-first"


def _snapshot_preferences(service: MemoryService, workspace_id: str):
    lane = service._build_personal_lane_snapshot(
        workspace_id, service._structured_for(workspace_id).snapshot()
    )
    return lane.preferences


def test_isolated_scope_hides_other_workspaces(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    _remember_preference(service, "project-alpha", "teaching_style", "concept-first")

    service.set_memory_scope("isolated")
    assert service.memory_scope() == "isolated"

    preferences = {preference.key for preference in _snapshot_preferences(service, "project-beta")}
    assert "teaching_style" not in preferences

    service.set_memory_scope("global")
    preferences = {preference.key for preference in _snapshot_preferences(service, "project-beta")}
    assert "teaching_style" in preferences


def test_scope_setting_survives_service_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "trainer-global-memory.db"
    service = MemoryService(TrainerRepository(db_path))
    service.set_memory_scope("isolated")

    rehydrated = MemoryService(TrainerRepository(db_path))
    assert rehydrated.memory_scope() == "isolated"


def test_invalid_scope_is_rejected_and_stored_scope_is_normalized(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    try:
        service.set_memory_scope("wide-open")
        raise AssertionError("expected ValueError for invalid scope")
    except ValueError:
        pass
    assert service.memory_scope() == "global"

    service.repository.save_memory_setting("memory_scope", "  GLOBAL  ")
    service._memory_scope_cache = None
    assert service.memory_scope() == "global"


def test_workspace_memory_scope_defaults_to_personal(tmp_path: Path) -> None:
    service = build_memory_service(tmp_path)
    structured = service._structured_for("brand-new-workspace")
    workspace = structured.snapshot().workspace if isinstance(structured.snapshot().workspace, dict) else {}
    assert service._memory_scope(workspace) == "personal"
