"""Task-level token cost ledger (P1 §四: 统一成本账本).

Records one JSONL entry per agentic turn so token spend, tool usage and
stop reasons stay auditable per workspace. Entries carry Trainer-side
*estimates* (chars/4) unless a future provider-reported usage is attached —
the field name says `estimate` so nobody mistakes it for provider truth.

The ledger is append-only and failure-tolerant: a full or unwritable disk
must never break a coaching turn.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("trainer.llm.cost_ledger")

_MAX_ENTRY_BYTES = 16_000
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_workspace_segment(workspace_id: str) -> str:
    cleaned = _SAFE_SEGMENT.sub("-", str(workspace_id or "").strip()).strip(".-")
    return cleaned[:80] or "workspace"


class CostLedger:
    """Append-only JSONL ledger of estimated task-level token usage."""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = Path(storage_dir)

    def _ledger_path(self, workspace_id: str) -> Path:
        return self._storage_dir / f"{_safe_workspace_segment(workspace_id)}.jsonl"

    def record(
        self,
        *,
        workspace_id: str,
        session_id: str | None = None,
        kind: str = "agentic_turn",
        model: str | None = None,
        prompt_tokens_estimate: int = 0,
        reply_tokens_estimate: int = 0,
        tool_call_count: int = 0,
        stop_reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Append one entry. Returns the written entry, or None on failure."""

        entry = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "workspace_id": str(workspace_id or "").strip(),
            "session_id": str(session_id or "").strip() or None,
            "kind": str(kind or "agentic_turn"),
            "model": str(model or "").strip() or None,
            "estimate": "chars/4",
            "prompt_tokens_estimate": max(0, int(prompt_tokens_estimate or 0)),
            "reply_tokens_estimate": max(0, int(reply_tokens_estimate or 0)),
            "tool_call_count": max(0, int(tool_call_count or 0)),
            "stop_reason": str(stop_reason or "").strip() or None,
        }
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            path = self._ledger_path(workspace_id)
            line = json.dumps(entry, ensure_ascii=False)
            if len(line.encode("utf-8")) > _MAX_ENTRY_BYTES:
                entry["stop_reason"] = (entry["stop_reason"] or "")[:200]
                line = json.dumps(entry, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return entry
        except OSError as exc:
            logger.warning("Cost ledger write failed for %s: %s", workspace_id, exc)
            return None

    def read_tail(self, workspace_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Newest-first bounded read; missing or damaged files read as empty."""

        bounded = max(1, min(int(limit or 50), 500))
        try:
            lines = self._ledger_path(workspace_id).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        entries: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= bounded:
                break
        return entries
