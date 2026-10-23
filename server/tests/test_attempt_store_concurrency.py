"""T-0031: evidence recording must be serialized per store.

Two racing ``record_evidence`` calls (one passed, one failed, same artifact)
must leave exactly ONE live evidence row: the later transaction sees the
earlier writer's row inside the same IMMEDIATE transaction and supersedes it.
The unlocked scan-then-write left both rows live, keeping a stale ``passed``
evidence verified after a newer failed evaluation.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app.training.attempt_store import AttemptStore


class RecordEvidenceConcurrencyTests(unittest.TestCase):
    def test_racing_evidence_writers_leave_exactly_one_live_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "attempts.db"
            store = AttemptStore(str(db_path))
            attempt = store.start_attempt(
                workspace_id="ws-concurrency",
                card_id="card-1",
                file_path="lesson.py",
                file_hash="hash-v1",
            )
            attempt_id = attempt["attempt_id"]

            # Force the unlocked pre-fix implementation into its bad
            # interleaving: both writers complete their supersede scan before
            # either writes. The hardened implementation no longer scans via
            # this helper, so the barrier simply never engages.
            scan_entered: list[int] = []
            first = threading.Event()
            second = threading.Event()
            real_scan = store.list_evidence_rows

            def racing_scan(attempt_id_arg: str) -> list[sqlite3.Row]:
                scan_entered.append(1)
                if len(scan_entered) == 1:
                    second.set()
                    first.wait(timeout=5)
                else:
                    first.set()
                    second.wait(timeout=5)
                return real_scan(attempt_id_arg)

            original_scan = store.list_evidence_rows
            store.list_evidence_rows = racing_scan  # type: ignore[method-assign]
            try:
                results: list[dict | None] = []
                errors: list[BaseException] = []

                def record(result: str) -> None:
                    try:
                        results.append(
                            store.record_evidence(
                                attempt_id=attempt_id,
                                caller_workspace_id="ws-concurrency",
                                artifact_hash="hash-v1",
                                result=result,
                                trust_level="controlled_check",
                                runner_version=f"runner-{result}",
                            )
                        )
                    except BaseException as exc:  # surfaced below
                        errors.append(exc)

                threads = [
                    threading.Thread(target=record, args=("passed",)),
                    threading.Thread(target=record, args=("failed",)),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
                self.assertFalse(errors, f"record_evidence raised: {errors}")
                self.assertEqual(len(results), 2)
                self.assertTrue(all(item is not None for item in results))
            finally:
                store.list_evidence_rows = original_scan  # type: ignore[method-assign]

            live = [
                item
                for item in store.list_evidence(attempt_id)
                if item.get("artifact_hash") == "hash-v1"
                and not item.get("superseded_by_evidence_id")
            ]
            self.assertEqual(
                len(live),
                1,
                "racing writers must serialize: exactly one live evidence row",
            )
            fresh_attempt = store.get_attempt(attempt_id)
            self.assertEqual(
                fresh_attempt.get("status") == "verified",
                live[0].get("result") == "passed",
                "attempt status must reflect the surviving evidence result",
            )


if __name__ == "__main__":
    unittest.main()
