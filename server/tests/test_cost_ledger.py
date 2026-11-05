"""Cost ledger: append-only estimated token usage per workspace (P1 §四)."""

from __future__ import annotations

import json
from pathlib import Path

from app.llm.cost_ledger import CostLedger


def _read_entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_record_appends_and_tail_reads_newest_first(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "cost-ledger")
    first = ledger.record(
        workspace_id="workspace-a",
        session_id="session-1",
        kind="agentic_turn",
        model="demo-model",
        prompt_tokens_estimate=120,
        reply_tokens_estimate=40,
        tool_call_count=2,
        stop_reason="completed",
    )
    assert first is not None
    assert first["prompt_tokens_estimate"] == 120
    assert first["estimate"] == "chars/4"

    ledger.record(
        workspace_id="workspace-a",
        session_id="session-1",
        prompt_tokens_estimate=200,
        reply_tokens_estimate=10,
        tool_call_count=0,
        stop_reason="completed",
    )

    tail = ledger.read_tail("workspace-a", limit=10)
    assert tail[0]["prompt_tokens_estimate"] == 200  # newest first
    assert tail[1]["tool_call_count"] == 2
    assert all(entry["workspace_id"] == "workspace-a" for entry in tail)


def test_workspaces_are_isolated_and_missing_reads_empty(tmp_path: Path) -> None:
    ledger = CostLedger(tmp_path / "cost-ledger")
    ledger.record(workspace_id="workspace-a", prompt_tokens_estimate=5)
    assert ledger.read_tail("workspace-b") == []
    entries = ledger.read_tail("workspace-a")
    assert len(entries) == 1

    # Workspace ids are file-safe segments, never path escapes.
    ledger.record(workspace_id="../escape")
    files = [p.name for p in (tmp_path / "cost-ledger").iterdir()]
    assert all("/" not in name and name not in {"..", "."} for name in files)


def test_turn_boundary_recorder_is_failure_tolerant() -> None:
    from app.api.runtime import TrainerRuntime

    runtime = TrainerRuntime.__new__(TrainerRuntime)
    runtime.cost_ledger = None
    # Must not raise without a ledger.
    runtime.record_agentic_cost_entry(
        workspace_id="w", session_id=None, outcome={"token_usage": {}}
    )

    class BrokenLedger:
        def record(self, **_kwargs):
            raise OSError("disk full")

    runtime.cost_ledger = BrokenLedger()
    runtime.record_agentic_cost_entry(
        workspace_id="w",
        session_id="s",
        outcome={"token_usage": {"prompt_tokens_estimate": 5}, "stop_reason": "completed"},
    )
