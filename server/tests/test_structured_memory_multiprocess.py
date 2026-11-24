"""Two VS Code windows on one LibraryRoot run two sidecars.

Each sidecar keeps its own in-memory copy of a workspace's structured memory,
and the stored record is one JSON object. A whole-object write from the second
process used to erase whatever the first one had just written. These tests
drive two ``MemoryService`` instances over one database — the same shape as two
sidecars — and check that a write only applies the parts it changed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from app.core.models import TrainingCardCandidateSnapshot
from app.db.repository import TrainerRepository
from app.memory.service import MemoryService, StructuredMemoryService

WORKSPACE = "workspace-two-windows"


def two_sidecars(tmp_path: Path) -> tuple[TrainerRepository, MemoryService, MemoryService]:
    """One database, two memory services: two windows, two sidecars."""
    repository = TrainerRepository(tmp_path / "trainer-multi-window.db")
    return repository, MemoryService(repository), MemoryService(repository)


def read_stored(repository: TrainerRepository) -> tuple[int, dict]:
    entry = repository.load_structured_memory_entry(WORKSPACE)
    assert entry is not None
    payload, revision = entry
    return revision, payload


def card(card_id: str, title: str) -> TrainingCardCandidateSnapshot:
    return TrainingCardCandidateSnapshot(
        card_id=card_id,
        card_type="practice",
        title=title,
        status="active",
    )


def test_a_write_from_the_second_sidecar_keeps_the_first_sidecars_keys(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    # Both windows have the workspace open, so each loaded it independently.
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.upsert_card(WORKSPACE, card("card-from-window-a", "Card A"))
    revision_after_a, after_a = read_stored(repository)
    assert [entry["card_id"] for entry in after_a["training_cards"]] == ["card-from-window-a"]

    # Window B's copy predates A's write. Its reflection must not erase A's card.
    window_b.record_reflection(
        "task-b",
        "reflection-from-window-b",
        workspace_id=WORKSPACE,
    )

    revision, stored = read_stored(repository)
    assert revision == revision_after_a + 1, "each write advances the revision once"
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["card-from-window-a"]
    assert any(
        "reflection-from-window-b" in str(reflection) for reflection in stored["reflections"]
    )


def test_the_other_sidecar_keeps_the_key_it_wrote_before(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.upsert_card(WORKSPACE, card("card-a1", "First"))
    window_b.record_reflection("task-b", "B reflection", workspace_id=WORKSPACE)
    revision_after_b, _ = read_stored(repository)

    # Window A adds another card from its stale copy; B's reflection survives.
    window_a.upsert_card(WORKSPACE, card("card-a2", "Second"))

    revision, stored = read_stored(repository)
    assert revision == revision_after_b + 1
    assert sorted(entry["card_id"] for entry in stored["training_cards"]) == [
        "card-a1",
        "card-a2",
    ]
    assert any("B reflection" in str(reflection) for reflection in stored["reflections"])


def test_two_sidecars_appending_to_the_same_list_keep_both_entries(tmp_path: Path) -> None:
    repository, window_a, window_b = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    window_b.snapshot(WORKSPACE)

    window_a.record_reflection("task-a", "A reflection", workspace_id=WORKSPACE)
    window_b.record_reflection("task-b", "B reflection", workspace_id=WORKSPACE)

    _, stored = read_stored(repository)
    summaries = {reflection.get("summary") for reflection in stored["reflections"]}
    assert summaries == {"A reflection", "B reflection"}


def test_a_single_sidecar_still_writes_what_it_loaded(tmp_path: Path) -> None:
    repository, window_a, _ = two_sidecars(tmp_path)
    window_a.snapshot(WORKSPACE)
    revision_before, _ = read_stored(repository)

    window_a.upsert_card(WORKSPACE, card("only-card", "Only"))

    revision, stored = read_stored(repository)
    assert revision == revision_before + 1
    # No other writer: the stored object is exactly the state the service
    # exports (a merge would have been a no-op, not a different shape).
    assert stored == window_a._structured_for(WORKSPACE).export_state()
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["only-card"]


def test_an_existing_database_gains_the_revision_column(tmp_path: Path) -> None:
    # A database written before revisions existed must keep its data and gain
    # the column the merge reads, without a manual migration step.
    database = tmp_path / "trainer-legacy.db"
    legacy_payload = json.dumps(StructuredMemoryService().export_state())
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE structured_memory (workspace_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO structured_memory (workspace_id, payload) VALUES (?, ?)",
        (WORKSPACE, legacy_payload),
    )
    connection.commit()
    connection.close()

    repository = TrainerRepository(database)
    entry = repository.load_structured_memory_entry(WORKSPACE)
    assert entry is not None
    payload, revision = entry
    assert revision == 0
    assert payload == json.loads(legacy_payload)

    service = MemoryService(repository)
    service.upsert_card(WORKSPACE, card("after-migration", "After migration"))
    revision, stored = read_stored(repository)
    assert revision == 1
    assert [entry["card_id"] for entry in stored["training_cards"]] == ["after-migration"]


# A separate OS process is the real two-window shape (two sidecars), which
# in-process instances can only approximate: caches, connections and the
# write lock are all per process.
_WRITER_SCRIPT = """
import sys
import time
from pathlib import Path

from app.db.repository import TrainerRepository
from app.memory.service import MemoryService

database, workspace, worker, count, ready_dir, go_file = sys.argv[1:7]
service = MemoryService(TrainerRepository(Path(database)))
# Load the workspace BEFORE any writer starts, exactly like sidecars launched
# together: every process must hold a genuinely stale baseline.
service.snapshot(workspace)
Path(ready_dir, worker).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 60
while not Path(go_file).exists():
    if time.monotonic() > deadline:
        raise SystemExit("go signal never arrived")
    time.sleep(0.01)
for index in range(int(count)):
    service.record_reflection(
        f"{worker}-task-{index}",
        f"{worker} reflection {index}",
        workspace_id=workspace,
    )
"""


def test_separate_processes_over_one_database_keep_every_write(tmp_path: Path) -> None:
    """Three real processes load the same empty workspace, then all write.

    A whole-object write from any of them used to erase the reflections the
    others had already persisted.
    """
    database = tmp_path / "trainer-processes.db"
    workspace_id = "workspace-processes"
    workers = 3
    per_worker = 4
    TrainerRepository(database).save_structured_memory(
        workspace_id, StructuredMemoryService().export_state()
    )

    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    go_file = tmp_path / "go"
    server_root = Path(__file__).resolve().parents[1]
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _WRITER_SCRIPT,
                str(database),
                workspace_id,
                f"worker-{index}",
                str(per_worker),
                str(ready_dir),
                str(go_file),
            ],
            cwd=server_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        for index in range(workers)
    ]
    try:
        deadline = time.monotonic() + 90
        while len(list(ready_dir.iterdir())) < workers:
            exited = [child.pid for child in children if child.poll() is not None]
            assert not exited, f"a writer exited before loading: pids {exited}"
            assert time.monotonic() < deadline, "writers did not load the workspace in time"
            time.sleep(0.02)
        go_file.write_text("go", encoding="utf-8")
        for child in children:
            _stdout, stderr = child.communicate(timeout=90)
            assert child.returncode == 0, stderr
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)

    stored = TrainerRepository(database).load_structured_memory(workspace_id)
    assert stored is not None
    task_ids = {item["task_id"] for item in stored["reflections"]}
    assert task_ids == {
        f"worker-{worker}-task-{index}"
        for worker in range(workers)
        for index in range(per_worker)
    }
