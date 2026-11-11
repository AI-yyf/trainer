"""Structured memory must follow the provisioned project context.

A project can be addressed by its folder path (the visible chat session) or by
its provisioned context id (training/plan writes). Both must share one memory
row; otherwise a due review or mastery written by training never reaches the
Learning surface of the path-based session.
"""

from __future__ import annotations

from pathlib import Path

from app.core.models import utc_now_iso
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService, StructuredMemoryService

LEGACY_PATH = "/Users/learner/project"
CONTEXT_ID = "context-test-1"


def _repository(tmp_path: Path) -> TrainerRepository:
    repository = TrainerRepository(tmp_path / "trainer-memory-alias.db")
    with repository._connect() as connection:
        connection.execute(
            "INSERT INTO workspace_context_aliases (alias, context_id, created_at) VALUES (?, ?, ?)",
            (LEGACY_PATH, CONTEXT_ID, utc_now_iso()),
        )
    return repository


def test_snapshot_reads_context_memory_through_the_legacy_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    structured = StructuredMemoryService()
    structured.remember_preference("answer_mode", "hands_on", source="settings")
    repository.save_structured_memory(CONTEXT_ID, structured.export_state())

    service = MemoryService(repository)
    lane = service._structured_for(LEGACY_PATH).snapshot()

    assert [preference.key for preference in lane.preferences] == ["answer_mode"]
    assert lane.preferences[0].value == "hands_on"


def test_persisting_through_the_legacy_path_writes_the_context_row(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    service = MemoryService(repository)
    service._structured_for(LEGACY_PATH).remember_preference("review_cadence", "daily", source="settings")
    service._persist_structured(LEGACY_PATH)

    context_row = repository.load_structured_memory(CONTEXT_ID) or {}
    path_row = repository.load_structured_memory(LEGACY_PATH)
    assert [preference["key"] for preference in context_row.get("preferences", [])] == [
        "review_cadence"
    ]
    assert path_row is None


def test_unaliased_workspace_stays_unchanged(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    service = MemoryService(repository)
    service._structured_for("plain-workspace").remember_preference(
        "answer_mode", "concept_first", source="coach-turn"
    )
    service._persist_structured("plain-workspace")

    row = repository.load_structured_memory("plain-workspace") or {}
    assert [preference["key"] for preference in row.get("preferences", [])] == ["answer_mode"]
    assert repository.load_structured_memory(CONTEXT_ID) is None
