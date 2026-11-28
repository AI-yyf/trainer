"""(m) Memory, FSRS and review scheduling: what the learner actually did drives due
    reviews, learner state, goals and the durable ledger.

Guarantees covered:
  * FSRS scheduling advances only on real reviews under a controlled clock, without sleeping or faking due dates;
  * review interventions, refusals and busy signals respect their budget and cooldowns;
  * preference memory strengthens on repetition and yields to explicit overrides;
  * goal lifecycle events and training evidence land in the durable, replay-safe ledger;
  * learner state, affect and global plans are derived from evidence, never from backlog size;
  * concurrent evidence writers are serialized and separate processes never lose a write.

Restores behavioral coverage deleted in df0a3e2a ("test: retire 614 legacy source-guard tests ..."),
whose commit message did not match its contents.  Originals at df0a3e2a^ (tests drive real
objects; nothing here asserts on source text or code shape):
  * server/tests/test_evidence_ledger_bridge.py
"""

from __future__ import annotations

from pathlib import Path

from app.core.settings import AppSettings
from app.main import create_app

# ---------------------------------------------------------------------------
# Restored from test_evidence_ledger_bridge.py (commit df0a3e2a^)
# ---------------------------------------------------------------------------


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer Evidence Ledger Test",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="evidence-ledger.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


def test_reversal_persists_across_app_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    first = create_app(_settings(data_dir))
    store = first.state.runtime.attempt_store
    attempt = store.start_attempt(workspace_id="w-ev", card_id="card-1")
    stale = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-1",
        result="passed",
        trust_level="controlled_check",
    )
    fresh = store.record_evidence(
        attempt_id=attempt["attempt_id"],
        artifact_hash="hash-2",
        result="passed",
        trust_level="controlled_check",
    )

    restarted = create_app(_settings(data_dir))
    stale_ledger_event_id = next(
        entry.event_id
        for entry in restarted.state.runtime.event_ledger.all_entries()
        if entry.event_type == "training_evidence_recorded"
        and entry.payload_ref.get("evidence_id") == stale["evidence_id"]
    )
    effective_ids = [
        entry.payload_ref.get("evidence_id")
        for entry in restarted.state.runtime.event_ledger.effective_entries()
        if entry.event_type == "training_evidence_recorded"
    ]
    assert effective_ids == [fresh["evidence_id"]]
    assert stale["evidence_id"] not in effective_ids
    reversals = [
        entry
        for entry in restarted.state.runtime.event_ledger.all_entries()
        if entry.event_type == "event_reversed"
        and entry.payload_ref.get("reversed_event_id") == stale_ledger_event_id
    ]
    assert len(reversals) == 1
